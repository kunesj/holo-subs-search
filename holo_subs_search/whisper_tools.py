from __future__ import annotations

import pathlib
from typing import Literal

import openai

# https://pypi.org/project/openai-whisper/
# Size   Required VRAM  Relative speed
# tiny   ~1 GB          ~10x
# base   ~1 GB          ~7x
# small  ~2 GB          ~4x
# medium ~5 GB          ~2x
# large  ~10 GB          1x
ModelSize = Literal["tiny", "small", "base", "medium", "large"]

# Audio formats that are supported by Whisper
WHISPER_AUDIO_FORMATS = ["flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm"]


def model_size_and_audio_lang_to_model(model_size: ModelSize, audio_lang: str | None = None) -> str:
    match model_size, audio_lang:
        case "tiny", "en":
            return "Systran/faster-whisper-tiny.en"
        case "tiny", _:
            return "Systran/faster-whisper-tiny"

        case "base", "en":
            return "Systran/faster-whisper-base.en"
        case "base", _:
            return "Systran/faster-whisper-base"

        case "small", "en":
            return "Systran/faster-whisper-small.en"
        case "small", _:
            return "Systran/faster-whisper-small"

        case "medium", "en":
            return "Systran/faster-whisper-medium.en"
        case "medium", _:
            return "Systran/faster-whisper-medium"

        case "large", _:
            return "Systran/faster-whisper-large-v3"

    raise ValueError("No matching model found")


def audio_to_srt_subtitles(
    path: pathlib.Path,
    *,
    api_base_url: str,
    api_key: str,
    model: str | Literal["whisper-1"],
    language: str | None = None,
    prompt: str | None = None,
    temperature: float | None = None,
    timeout: str | None = None,
) -> str:
    """
    - See WHISPER_INPUT_FORMATS for supported formats
    - Whisper internally resamples audio to 16kHz, so the input does not have to be high quality
        https://dev.to/mxro/optimise-openai-whisper-api-audio-format-sampling-rate-and-quality-29fj
        https://github.com/openai/whisper/discussions/870#discussioncomment-4743438
    - I was unable to find if low bitrate has any negative effects
    """
    client = openai.OpenAI(api_key=api_key, base_url=api_base_url)

    with path.open("rb") as f:
        transcript = client.audio.transcriptions.create(
            file=f,
            model=model,
            language=openai.NOT_GIVEN if language is None else language,
            prompt=openai.NOT_GIVEN if prompt is None else prompt,
            response_format="srt",
            temperature=openai.NOT_GIVEN if temperature is None else temperature,
            timeout=openai.NOT_GIVEN if timeout is None else timeout,
        )

    if isinstance(transcript, str):
        return transcript
    return transcript.text
