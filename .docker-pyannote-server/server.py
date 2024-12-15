#!/usr/bin/env python3.11

from __future__ import annotations

import asyncio
import dataclasses
import io
import logging
import os
from typing import Annotated, cast

import numpy
import pyannote.audio
import pydub
import torch
import torchaudio
from fastapi import FastAPI, HTTPException, Query, Response, UploadFile
from pyannote.audio.pipelines.speaker_diarization import SpeakerDiarization

SpeakerEmbeddingsType = dict[str, list[float]]

_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

GPU_COUNT = torch.cuda.device_count()
GPU_PARALLEL_COUNT = int(os.getenv("GPU_PARALLEL_COUNT", default="1"))

CPU_COUNT = int(os.getenv("CPU_DEVICES", default="0"))
CPU_PARALLEL_COUNT = int(os.getenv("CPU_PARALLEL_COUNT", default="1"))

AUDIO_SEMAPHORE = asyncio.Semaphore(int(os.getenv("AUDIO_SEMAPHORE", default="12")))
DIARIZATION_SEMAPHORE = asyncio.Semaphore(int(os.getenv("DIARIZATION_SEMAPHORE", default="16")))


# ============================= DEVICES ===============================
# region


class CounterSemaphore(asyncio.Semaphore):
    def __init__(self, value: int = 1) -> None:
        self._capacity = value
        super().__init__(value=value)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def running(self) -> int:
        return max(self._capacity - self._value, 0)

    @property
    def waiting(self) -> int:
        return len([x for x in (self._waiters or ()) if not x.cancelled()])


@dataclasses.dataclass
class DeviceState:
    device: torch.device = dataclasses.field()
    # IMPORTANT: semaphore limit must be exactly 1! One pipeline object can't be executed from two different threads.
    #   Instead, create more device states for the same device!
    semaphore: CounterSemaphore = dataclasses.field(default_factory=lambda: CounterSemaphore(1))
    checkpoint: str | None = dataclasses.field(default=None)
    pipeline: SpeakerDiarization | None = dataclasses.field(default=None)
    # enforces order of states with same priority
    sequence: int = dataclasses.field(default=0)

    @property
    def priority(self) -> int:
        return self.semaphore.running + self.semaphore.waiting


DEVICE_STATES: dict[str, DeviceState] = {}

for idx in range(GPU_COUNT):
    for n in range(GPU_PARALLEL_COUNT):
        sequence = n
        DEVICE_STATES[f"cuda:{idx}:{sequence}"] = DeviceState(
            device=torch.device(f"cuda:{idx}"),
            sequence=sequence,
        )

for idx in range(CPU_COUNT):
    for n in range(CPU_PARALLEL_COUNT):
        sequence = 100 + n
        DEVICE_STATES[f"cpu:{idx}:{sequence}"] = DeviceState(
            device=torch.device("cpu"),
            sequence=sequence,
        )

if not DEVICE_STATES:
    raise RuntimeError("No devices available!")
_logger.info("DEVICE STATES: %s", ",".join(DEVICE_STATES.keys()))


# endregion
# ============================= DIARIZATION ===============================
# region


@dataclasses.dataclass
class DiarizationSegment:
    start: float
    end: float
    speaker: str


@dataclasses.dataclass
class Diarization:
    # configuration
    checkpoint: str
    segmentation_model: str | None
    segmentation_batch_size: int
    embedding_model: str | None
    embedding_batch_size: int
    embedding_exclude_overlap: bool
    clustering: str
    # result
    segments: list[DiarizationSegment]
    embeddings: dict[str, list[float]]


def _load_diarization_pipeline(
    *, device: torch.device, checkpoint: str, huggingface_token: str | None
) -> SpeakerDiarization:
    _logger.info("Loading diarization model pipeline: %s", checkpoint)

    pipeline = pyannote.audio.Pipeline.from_pretrained(
        checkpoint_path=checkpoint,
        use_auth_token=huggingface_token,
    )

    if not pipeline:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Diarization checkpoint could not be loaded! "
                f"huggingface_token {huggingface_token!r} might be missing, invalid, "
                f"or user conditions of the model {checkpoint!r} were not accepted yet."
            ),
        )
    elif not isinstance(pipeline, SpeakerDiarization):
        raise HTTPException(
            status_code=400,
            detail="Unexpected pipeline loaded!",
        )

    _logger.info("Moving diarization model to: %s", device)
    pipeline.to(device)

    return cast(SpeakerDiarization, pipeline)


def _run_diarization_pipeline(
    pipeline: SpeakerDiarization,
    wav_stream: io.BytesIO,
) -> tuple[list[DiarizationSegment], SpeakerEmbeddingsType]:
    _logger.info("Diarizating audio file...")
    waveform, sample_rate = torchaudio.load(wav_stream)
    diarization, raw_embeddings = pipeline({"waveform": waveform, "sample_rate": sample_rate}, return_embeddings=True)

    _logger.info("Reading segments...")
    segments = [
        DiarizationSegment(start=turn.start, end=turn.end, speaker=speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]

    _logger.info("Reading embeddings...")
    embeddings = {}
    for idx in range(raw_embeddings.shape[0]):
        if numpy.any(numpy.isnan(raw_embeddings[idx, :])):
            continue
        embeddings[f"SPEAKER_{idx:0>2}"] = raw_embeddings[idx, :].flatten().tolist()

    return segments, embeddings


async def run_diarization_on_device(
    device: str,
    wav_stream: io.BytesIO,
    checkpoint: str,
    huggingface_token: str | None = None,
) -> Diarization:
    """
    - loads and runs cached pipeline on the specified device
    - async safe - multiple calls wait until first finishes
    """
    _logger.info("Queuing diarization: %s, %s", device, checkpoint)
    state = DEVICE_STATES[device]
    async with state.semaphore:
        # load cached pipeline

        if state.checkpoint is None or state.checkpoint != checkpoint:
            state.checkpoint = state.pipeline = None
            try:
                state.checkpoint = checkpoint
                state.pipeline = await asyncio.to_thread(
                    _load_diarization_pipeline,
                    device=state.device,
                    checkpoint=checkpoint,
                    huggingface_token=huggingface_token,
                )
            except Exception:
                state.checkpoint = state.pipeline = None
                raise

        # run diarization

        segments, embeddings = await asyncio.to_thread(
            _run_diarization_pipeline, pipeline=state.pipeline, wav_stream=wav_stream
        )

        # return diarization object

        return Diarization(
            # config
            checkpoint=checkpoint,
            segmentation_model=(
                state.pipeline.segmentation_model if isinstance(state.pipeline.segmentation_model, str) else None
            ),
            segmentation_batch_size=state.pipeline.segmentation_batch_size,
            embedding_model=state.pipeline.embedding if isinstance(state.pipeline.embedding, str) else None,
            embedding_batch_size=state.pipeline.embedding_batch_size,
            embedding_exclude_overlap=state.pipeline.embedding_exclude_overlap,
            clustering=state.pipeline.klustering,
            # results
            segments=segments,
            embeddings=embeddings,
        )


def get_next_device() -> str:
    """
    Returns device with that should process next task.
    """
    sorted_devices = sorted(
        DEVICE_STATES.keys(),
        key=lambda device: (DEVICE_STATES[device].priority, DEVICE_STATES[device].sequence),
    )
    return sorted_devices[0]


# endregion
# ============================= DIARIZATION ===============================
# region


def _audio_to_wav(source: io.BytesIO, name: str) -> io.BytesIO:
    _logger.info("Converting audio to wav: %s", name)

    sound = pydub.AudioSegment.from_file(source, name.split(".")[-1])
    wav_stream = io.BytesIO()
    sound.export(wav_stream, format="wav")

    wav_stream.seek(0)
    return wav_stream


async def file_to_wav(file: UploadFile) -> io.BytesIO:
    """
    NOTE: Loading audio into memory speeds up the diarization.
    """
    stream = io.BytesIO(await file.read())
    name = file.filename

    if not name.endswith(".wav"):
        async with AUDIO_SEMAPHORE:
            stream = await asyncio.to_thread(_audio_to_wav, source=stream, name=name)

    return stream


# endregion
# ============================= API ===============================
# region


app = FastAPI()


@app.get("/healthcheck")
def healthcheck() -> Response:
    return Response(status_code=200)


# Can be tested with:
# curl -X POST -F "file=@/home/????/????/599.m4a"
# "http://0.0.0.0:8010/diarization?checkpoint=pyannote/speaker-diarization-3.1&huggingface_token=????"
@app.post("/diarization")
async def diarization(
    file: UploadFile,
    checkpoint: Annotated[str, Query()],
    huggingface_token: Annotated[str | None, Query()] = None,
) -> Diarization:
    """
    Parameters:
        file:
        - Supports all audio formats that are supported by `pydub`, but using `wav` will be faster,
          because the file will not have to be converted into it.

        checkpoint:
        - Accept https://hf.co/pyannote/segmentation-3.0 user conditions
        - Accept https://hf.co/pyannote/speaker-diarization-3.1 user conditions
        - Use: `pyannote/speaker-diarization-3.1`

        huggingface_token:
        - Create access token at https://hf.co/settings/tokens and use it when calling this endpoint

    Probably doesn't handle switching between models or concurrent requests very well.

    Returns mean embeddings for each speaker to allow identifying speaker between multiple files.
    Similarity of speakers/embeddings can then be computed with:
    >>> from scipy.spatial.distance import cdist
    >>> embedding1: list[float]
    >>> embedding2: list[float]
    >>> distance = cdist(embedding1, embedding2, metric="cosine")
    """
    async with DIARIZATION_SEMAPHORE:
        wav_stream = await file_to_wav(file)
        return await run_diarization_on_device(
            device=get_next_device(),
            wav_stream=wav_stream,
            checkpoint=checkpoint,
            huggingface_token=huggingface_token,
        )


# endregion
