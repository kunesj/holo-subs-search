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
PYANNOTE_BASE_URLS = get_env("PYANNOTE_BASE_URLS", str, default="http://localhost:8010/").split(",")
HUGGINGFACE_TOKEN = get_env("HUGGINGFACE_TOKEN", str, default=None)

# Url of OpenAI-compatible API with whisper support.
WHISPER_BASE_URLS = get_env("WHISPER_BASE_URLS", lambda x: x.split(","), default="http://localhost:8000/v1/")
# can be empty/placeholder for local api
WHISPER_API_KEYS = get_env("WHISPER_API_KEYS", lambda x: x.split(","), default="placeholder")

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
PYANNOTE_PARALLEL_COUNTS = get_env(
    "PYANNOTE_PARALLEL_COUNTS",
    lambda x: [int(y) for y in x.split(",")],
    default=",".join(str(VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT) for _ in PYANNOTE_BASE_URLS),
)
WHISPER_PARALLEL_COUNTS = get_env(
    "WHISPER_PARALLEL_COUNTS",
    lambda x: [int(y) for y in x.split(",")],
    default=",".join("1" for _ in PYANNOTE_BASE_URLS),
)

# Validators

if len(PYANNOTE_BASE_URLS) != len(PYANNOTE_PARALLEL_COUNTS):
    raise RuntimeError("Number of items in PYANNOTE_BASE_URLS must be the same as in PYANNOTE_PARALLEL_COUNTS")

if not (len(WHISPER_BASE_URLS) == len(WHISPER_API_KEYS) == len(WHISPER_PARALLEL_COUNTS)):
    raise RuntimeError(
        "Number of items in WHISPER_BASE_URL must be the same as in WHISPER_API_KEY and WHISPER_PARALLEL_COUNTS"
    )
