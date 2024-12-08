#!/usr/bin/env python3.11

import dataclasses
import io
import logging
from typing import Annotated, Any

import numpy
import pyannote.audio
import pydub
import torch
from fastapi import FastAPI, HTTPException, Query, Response, UploadFile

_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

CACHE: dict[str, Any] = {
    "diarization_pipeline": None,
    "diarization_model": None,
    "embedding_pipeline": None,
    "embedding_model": None,
}
TORCH_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_logger.info("TORCH_DEVICE: %s", TORCH_DEVICE)


def load_diarization_pipeline(model: str, huggingface_token: str | None) -> pyannote.audio.Pipeline:
    if model == CACHE["diarization_model"]:
        _logger.info("Using cached diarization model pipeline: %s", model)
        pipeline = CACHE["diarization_pipeline"]

    else:
        _logger.info("Loading diarization model pipeline: %s", model)
        CACHE["diarization_pipeline"] = None
        CACHE["diarization_model"] = None

        pipeline = pyannote.audio.Pipeline.from_pretrained(
            checkpoint_path=model,
            use_auth_token=huggingface_token,
        )

        if not pipeline:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Diarization Model could not be loaded! "
                    f"huggingface_token {huggingface_token!r} might be missing, invalid, "
                    f"or user conditions of the model {model!r} were not accepted yet."
                ),
            )

        _logger.info("Moving diarization model to: %s", TORCH_DEVICE)
        pipeline.to(TORCH_DEVICE)

        CACHE["diarization_pipeline"] = pipeline
        CACHE["diarization_model"] = model

    return pipeline


def load_embedding_pipeline(model: str, huggingface_token: str | None) -> pyannote.audio.Pipeline:
    if model == CACHE["embedding_model"]:
        _logger.info("Using cached embedding model pipeline: %s", model)
        pipeline = CACHE["embedding_pipeline"]

    else:
        _logger.info("Loading embedding model pipeline: %s", model)
        CACHE["embedding_pipeline"] = None
        CACHE["embedding_model"] = None

        pipeline = pyannote.audio.pipelines.speaker_verification.PretrainedSpeakerEmbedding(
            embedding="speechbrain/spkrec-ecapa-voxceleb",
            use_auth_token=huggingface_token,
        )

        if not pipeline:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Embedding Model could not be loaded! "
                    f"huggingface_token {huggingface_token!r} might be missing, invalid, "
                    f"or user conditions of the model {model!r} were not accepted yet."
                ),
            )

        _logger.info("Moving embedding model to: %s", TORCH_DEVICE)
        pipeline.to(TORCH_DEVICE)

        CACHE["embedding_pipeline"] = pipeline
        CACHE["embedding_model"] = model

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
    diarization_model: str
    diarization: list[DiarizationSegment]
    embedding_model: str
    embeddings: dict[str, list[float]]


app = FastAPI()


@app.get("/healthcheck")
def healthcheck() -> Response:
    return Response(status_code=200)


# Can be tested with:
# curl -X POST -F "file=@/home/????/????/599.m4a" "http://0.0.0.0:8001/diarization?huggingface_token=????"
@app.post("/diarization")
async def diarization(
    file: UploadFile,
    diarization_model: Annotated[str, Query()] = "pyannote/speaker-diarization-3.1",
    embedding_model: Annotated[str, Query()] = "speechbrain/spkrec-ecapa-voxceleb",
    huggingface_token: Annotated[str | None, Query()] = None,
) -> DiarizationResponse:
    """
    To use the default diarization model:
    - Accept https://hf.co/pyannote/segmentation-3.0 user conditions
    - Accept https://hf.co/pyannote/speaker-diarization-3.1 user conditions
    - Create access token at https://hf.co/settings/tokens and use it when calling this endpoint

    Supports all audio formats that are supported by `pydub`, but using `wav` will be faster,
    because the file will not have to be converted into it.

    Probably doesn't handle switching between models or concurrent requests very well.

    Returns mean embeddings for each speaker to allow identifying speaker between multiple files.
    Similarity of speakers/embeddings can then be computed with:
    >>> from scipy.spatial.distance import cdist
    >>> embedding1: list[float]
    >>> embedding2: list[float]
    >>> distance = cdist(embedding1, embedding2, metric="cosine")
    """
    diarization_pipeline = load_diarization_pipeline(diarization_model, huggingface_token)
    embedding_pipeline = load_embedding_pipeline(embedding_model, huggingface_token)
    wav_stream = await file_to_wav_stream(file)

    # detect speakers
    # TODO: maybe check this for better results?
    #   https://github.com/pyannote/pyannote-audio/blob/develop/tutorials/community/offline_usage_speaker_diarization.ipynb
    #   https://github.com/wenet-e2e/wespeaker

    _logger.info("Diarizating audio file...")
    segments = [
        DiarizationSegment(start=turn.start, end=turn.end, speaker=speaker)
        for turn, _, speaker in diarization_pipeline(wav_stream).itertracks(yield_label=True)
    ]

    # compute speaker embeddings
    # based on https://github.com/pyannote/pyannote-audio/blob/develop/tutorials/speaker_verification.ipynb

    _logger.info("Calculating embeddings...")

    audio = pyannote.audio.Audio(sample_rate=16000, mono="downmix")
    embeddings: dict[str, list[float]] = {}

    for speaker in {x.speaker for x in segments}:
        # get embedding for every segment with the speaker

        speaker_embeddings: list[numpy.ndarray] = []

        for segment in segments:
            if segment.speaker != speaker:
                continue
            elif (segment.end - segment.start) < 0.1:
                # embedding generation usually fails for tiny segments
                continue

            waveform, sample_rate = audio.crop(wav_stream, pyannote.core.Segment(segment.start, segment.end))
            embedding = embedding_pipeline(waveform[None]).flatten()

            if numpy.any(numpy.isnan(embedding)):
                _logger.warning("Embedding not generated: %s: %s -> %s", speaker, segment.start, segment.end)
                continue

            speaker_embeddings.append(embedding)

        if not speaker_embeddings:
            _logger.error("No speaker embeddings generated: %s", speaker)
            continue

        # calculate mean embedding to fully describe the speaker with just one value
        # - https://www.reddit.com/r/LanguageTechnology/comments/st1si5/averaging_sentence_embeddings_to_create/
        # - https://en.wikipedia.org/wiki/Kernel_embedding_of_distributions
        # - https://github.com/RF5/simple-speaker-embedding

        mean_embedding = numpy.mean(speaker_embeddings, axis=0)
        embeddings[speaker] = mean_embedding.tolist()

    return DiarizationResponse(
        diarization_model=diarization_model,
        diarization=segments,
        embedding_model=embedding_model,
        embeddings=embeddings,
    )
