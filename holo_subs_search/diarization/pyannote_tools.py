from __future__ import annotations

import os
import pathlib
import urllib.parse

import requests

from .diarization import Diarization

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
EMBEDDING_MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def audio_to_diarization_response(
    path: pathlib.Path,
    *,
    api_base_url: str,
    diarization_model: str,
    embedding_model: str,
    huggingface_token: str | None = None,
    timeout: float | None = None,
) -> Diarization:
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

    return Diarization.model_validate(response.json())
