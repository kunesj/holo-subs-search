from __future__ import annotations

import mimetypes
import os
import pathlib
import urllib.parse

import aiohttp

from ..env_config import HUGGINGFACE_TOKEN, PYANNOTE_BASE_URLS, PYANNOTE_PARALLEL_COUNTS
from ..utils import CounterSemaphore
from .diarization import Diarization

PYANNOTE_SEMAPHORES = [CounterSemaphore(n) for n in PYANNOTE_PARALLEL_COUNTS]

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


def get_next_server() -> tuple[CounterSemaphore, str]:
    idx = PYANNOTE_SEMAPHORES.index(min(PYANNOTE_SEMAPHORES, key=lambda x: x.busyness))
    return PYANNOTE_SEMAPHORES[idx], PYANNOTE_BASE_URLS[idx]


async def audio_to_diarization_response(
    path: pathlib.Path,
    *,
    checkpoint: str,
    timeout: aiohttp.ClientTimeout | None = None,
) -> Diarization:
    """
    - Supports any format ffmpeg supports
    """
    semaphore, base_url = get_next_server()
    async with semaphore:
        params = {
            "checkpoint": checkpoint,
            "huggingface_token": HUGGINGFACE_TOKEN,
        }
        params = {k: v for k, v in params.items() if v is not None}

        async with aiohttp.ClientSession() as session:
            if mt := mimetypes.guess_type(path):
                content_type = mt[0]
            else:
                raise ValueError("Could not guess mimetype", path)

            data = aiohttp.FormData()
            data.add_field("file", path.open("rb"), filename=os.path.basename(path), content_type=content_type)

            response = await session.post(
                url=urllib.parse.urljoin(base_url, "diarization"),
                data=data,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()

            return Diarization.model_validate(await response.json())
