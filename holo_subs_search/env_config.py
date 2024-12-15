from __future__ import annotations

import os
from typing import Any, Callable

from .utils import Undefined, UndefinedType


def get_env(name: str, parser: Callable, *, default: UndefinedType | str | None = Undefined) -> Any:
    value = os.getenv(name, None)

    if value is not None and value.strip() == "":
        value = None

    if value is None and default is Undefined:
        raise RuntimeError(f"{name} env variable must be set!")

    return parser(default if value is None else value)


HOLODEX_API_KEY = get_env("HOLODEX_API_KEY", str)

# Url of pyannote-server built from this repo
PYANNOTE_BASE_URL = get_env("PYANNOTE_BASE_URL", str, default="http://localhost:8001/")
HUGGINGFACE_TOKEN = get_env("HUGGINGFACE_TOKEN", str, default=None)

# Url of OpenAI-compatible API with whisper support.
WHISPER_BASE_URL = get_env("WHISPER_BASE_URL", str, default="http://localhost:8000/v1/")
# can be empty/placeholder for local api
WHISPER_API_KEY = get_env("WHISPER_API_KEY", str, default="placeholder")

# Video processing

VIDEO_PROCESS_PARALLEL_COUNT = get_env("VIDEO_PROCESS_PARALLEL_COUNT", int, default="1")
VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT = get_env("VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT", int, default="1")
VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT = get_env("VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT", int, default="1")
# Don't touch this one. Raising just WHISPER_API_PARALLEL_COUNT is a lot better.
# One diarized transcription can generate many concurrent api calls, so raising this does not make sense.
VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT = get_env("VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT", int, default="1")

# API parallelism

HOLODEX_PARALLEL_COUNT = get_env("HOLODEX_PARALLEL_COUNT", int, default="1")
YTDL_PARALLEL_COUNT = get_env("YTDL_PARALLEL_COUNT", int, default=str(VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT))
PYANNOTE_PARALLEL_COUNT = get_env("PYANNOTE_PARALLEL_COUNT", int, default=str(VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT))
# Should be roughly equal to number of GPUs that whisper is using.
WHISPER_PARALLEL_COUNT = get_env("WHISPER_PARALLEL_COUNT", int, default="1")
