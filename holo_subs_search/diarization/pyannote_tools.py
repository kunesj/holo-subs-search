from __future__ import annotations

import os
import pathlib
import urllib.parse

import requests

from .diarization import Diarization

DIARIZATION_CHECKPOINT = "pyannote/speaker-diarization-3.1"
# - developed on 84fd25912480287da0247647c3d2b4853cb3ee5d
# - This just loads following config in pyannote:
#     pipeline:
#       name: pyannote.audio.pipelines.SpeakerDiarization
#       params:
#         clustering: AgglomerativeClustering
#         embedding: pyannote/wespeaker-voxceleb-resnet34-LM
#         embedding_batch_size: 32
#         embedding_exclude_overlap: true
#         segmentation: pyannote/segmentation-3.0
#         segmentation_batch_size: 32
#
#     params:
#       clustering:
#         method: centroid
#         min_cluster_size: 12
#         threshold: 0.7045654963945799
#       segmentation:
#         min_duration_off: 0.0


def audio_to_diarization_response(
    path: pathlib.Path,
    *,
    api_base_url: str,
    checkpoint: str,
    huggingface_token: str | None = None,
    timeout: float | None = None,
) -> Diarization:
    """
    - Supports any format ffmpeg supports
    """
    params = {
        "checkpoint": checkpoint,
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
