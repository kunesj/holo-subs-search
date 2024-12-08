from __future__ import annotations

import dataclasses
import os
import pathlib
import urllib.parse
from typing import Any, Self

import requests

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
EMBEDDING_MODEL = "speechbrain/spkrec-ecapa-voxceleb"


@dataclasses.dataclass
class DiarizationResponseSegment:
    start: float
    end: float
    speaker: str

    @classmethod
    def from_json(cls: type[Self], value: dict[str, Any]) -> Self:
        return cls(start=value["start"], end=value["end"], speaker=value["speaker"])

    def to_json(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "speaker": self.speaker}


@dataclasses.dataclass
class DiarizationResponse:
    diarization_model: str
    diarization: list[DiarizationResponseSegment]
    embedding_model: str
    embeddings: dict[str, list[float]]

    @classmethod
    def from_json(cls: type[Self], value: dict[str, Any]) -> Self:
        return cls(
            diarization_model=value["diarization_model"],
            diarization=[DiarizationResponseSegment.from_json(x) for x in value["diarization"]],
            embedding_model=value["embedding_model"],
            embeddings=value["embeddings"],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "diarization_model": self.diarization_model,
            "diarization": [x.to_json() for x in self.diarization],
            "embedding_model": self.embedding_model,
            "embeddings": self.embeddings,
        }


def audio_to_diarization_response(
    path: pathlib.Path,
    *,
    api_base_url: str,
    diarization_model: str,
    embedding_model: str,
    huggingface_token: str | None = None,
    timeout: float | None = None,
) -> DiarizationResponse:
    """
    - Supports any format ffmpeg supports
    """
    params = {
        "diarization_model": diarization_model,
        "embedding_model": embedding_model,
        "huggingface_token": huggingface_token,
    }
    params = {k: v for k, v in params.items() if v is not None}

    response = requests.post(
        url=urllib.parse.urljoin(api_base_url, "diarization"),
        files={"file": (os.path.basename(path), path.open("rb"))},
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()

    return DiarizationResponse.from_json(response.json())
