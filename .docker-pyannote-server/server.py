#!/usr/bin/env python3.11

import dataclasses
import io
import logging
from typing import Annotated, Any

import numpy
import pyannote.audio
import pydub
import torch
import torchaudio
from fastapi import FastAPI, HTTPException, Query, Response, UploadFile
from pyannote.audio.pipelines.speaker_diarization import SpeakerDiarization

_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

CACHE: dict[str, Any] = {
    "pipeline": None,
    "checkpoint": None,
}
TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_logger.info("TORCH_DEVICE: %s", TORCH_DEVICE)


def load_diarization_pipeline(*, checkpoint: str, huggingface_token: str | None) -> SpeakerDiarization:
    if checkpoint == CACHE["checkpoint"]:
        _logger.info("Using cached diarization model pipeline: %s", checkpoint)
        pipeline = CACHE["pipeline"]

    else:
        _logger.info("Loading diarization model pipeline: %s", checkpoint)
        CACHE.update(
            {
                "pipeline": None,
                "checkpoint": None,
            }
        )

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

        _logger.info("Moving diarization model to: %s", TORCH_DEVICE)
        pipeline.to(TORCH_DEVICE)

        CACHE.update(
            {
                "pipeline": pipeline,
                "checkpoint": checkpoint,
            }
        )

    return pipeline


async def file_to_wav_stream(file: UploadFile) -> io.BytesIO:
    file_stream = io.BytesIO(await file.read())

    if file.filename.endswith(".wav"):
        wav_stream = file_stream
    else:
        _logger.info("Converting uploaded file to wav")

        sound = pydub.AudioSegment.from_file(file_stream, file.filename.split(".")[-1])
        wav_stream = io.BytesIO()
        sound.export(wav_stream, format="wav")

    wav_stream.seek(0)
    return wav_stream


@dataclasses.dataclass
class DiarizationSegment:
    start: float
    end: float
    speaker: str


@dataclasses.dataclass
class DiarizationResponse:
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


app = FastAPI()


@app.get("/healthcheck")
def healthcheck() -> Response:
    return Response(status_code=200)


# Can be tested with:
# curl -X POST -F "file=@/home/????/????/599.m4a"
# "http://0.0.0.0:8001/diarization?checkpoint=pyannote/speaker-diarization-3.1&huggingface_token=????"
@app.post("/diarization")
async def diarization(
    file: UploadFile,
    checkpoint: Annotated[str, Query()],
    huggingface_token: Annotated[str | None, Query()] = None,
) -> DiarizationResponse:
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
    pipeline = load_diarization_pipeline(checkpoint=checkpoint, huggingface_token=huggingface_token)

    # preload audio into memory for faster processing
    waveform, sample_rate = torchaudio.load(await file_to_wav_stream(file))

    _logger.info("Diarizating audio file...")
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

    return DiarizationResponse(
        # config
        checkpoint=checkpoint,
        segmentation_model=pipeline.segmentation_model if isinstance(pipeline.segmentation_model, str) else None,
        segmentation_batch_size=pipeline.segmentation_batch_size,
        embedding_model=pipeline.embedding if isinstance(pipeline.embedding, str) else None,
        embedding_batch_size=pipeline.embedding_batch_size,
        embedding_exclude_overlap=pipeline.embedding_exclude_overlap,
        clustering=pipeline.klustering,
        # results
        segments=segments,
        embeddings=embeddings,
    )
