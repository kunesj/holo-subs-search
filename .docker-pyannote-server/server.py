#!/usr/bin/env python3.11

import io
import logging
import os
import pathlib
from typing import Annotated, Any

import pyannote.audio
import pydub
import torch
from fastapi import FastAPI, HTTPException, Query, Response, UploadFile
from typing_extensions import TypedDict  # can't be imported from typing, because of fastapi

_logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PIPELINE_CACHE: dict[str, Any] = {"pipeline": None, "model": None}
TORCH_CPU_PATH = pathlib.Path(os.path.dirname(os.path.realpath(__file__)), "./TORCH_CPU")
TORCH_CPU = bool(int(TORCH_CPU_PATH.read_text() if TORCH_CPU_PATH.exists() else "0"))
_logger.info("TORCH_CPU=%s", TORCH_CPU)

app = FastAPI()


@app.get("/healthcheck")
def healthcheck() -> Response:
    return Response(status_code=200)


class Track(TypedDict):
    start: float
    end: float
    speaker: str


class DiarizationResponse(TypedDict):
    tracks: list[Track]


@app.post("/diarization")
async def diarization(
    file: UploadFile,
    model: Annotated[str, Query()] = "pyannote/speaker-diarization-3.1",
    huggingface_token: Annotated[str | None, Query()] = None,
) -> DiarizationResponse:
    """
    To use the default model:
    - Accept https://hf.co/pyannote/segmentation-3.0 user conditions
    - Accept https://hf.co/pyannote/speaker-diarization-3.1 user conditions
    - Create access token at https://hf.co/settings/tokens and use it when calling this endpoint

    Supports all audio formats that are supported by `pydub`, but using `wav` will be faster,
    because the file will not have to be converted into it.

    Probably doesn't handle switching between models or concurrent requests very well.
    """

    # get/load model pipeline

    if model == PIPELINE_CACHE["model"]:
        _logger.info("Using cached model pipeline: %s", model)
        pipeline = PIPELINE_CACHE["pipeline"]

    else:
        _logger.info("Loading model pipeline: %s", model)
        PIPELINE_CACHE["pipeline"] = None
        PIPELINE_CACHE["model"] = None

        pipeline = pyannote.audio.Pipeline.from_pretrained(
            checkpoint_path=model,
            use_auth_token=huggingface_token,
        )

        if not pipeline:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Model could not be loaded! "
                    f"huggingface_token {huggingface_token!r} might be missing, invalid, "
                    f"or user conditions of the model {model!r} were not accepted yet."
                ),
            )

        if not TORCH_CPU:
            _logger.info("Moving model to GPU")
            pipeline.to(torch.device("cuda"))

        PIPELINE_CACHE["pipeline"] = pipeline
        PIPELINE_CACHE["model"] = model

    # convert file to wav stream

    file_stream = io.BytesIO(await file.read())

    if file.filename.endswith(".wav"):
        wav_stream = file_stream
    else:
        _logger.info("Converting uploaded file to wav")

        sound = pydub.AudioSegment.from_file(file_stream, file.filename.split(".")[-1])
        wav_stream = io.BytesIO()
        sound.export(wav_stream, format="wav")

    wav_stream.seek(0)

    # process audio file

    _logger.info("Processing audio file...")

    return {
        "tracks": [
            {"start": turn.start, "end": turn.end, "speaker": speaker}
            for turn, _, speaker in pipeline(wav_stream).itertracks(yield_label=True)
        ]
    }
