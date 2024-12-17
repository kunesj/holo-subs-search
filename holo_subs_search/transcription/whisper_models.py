from __future__ import annotations

from typing import Literal

# https://pypi.org/project/openai-whisper/
# Size   Required VRAM  Relative speed
# tiny   ~1 GB          ~10x
# base   ~1 GB          ~7x
# small  ~2 GB          ~4x
# medium ~5 GB          ~2x
# large  ~10 GB          1x
ModelSize = Literal["tiny", "small", "base", "medium", "large"]

# Improved version of Whisper with:
# - precise and verbatim speech recognition with accurate (crisp) word-level timestamps.
# - Aims to transcribe every spoken word exactly as it is, including fillers, pauses, stutters and false starts.
# - Lower chance of halucinations
# - The version for the faster-whisper does not guarantee precision of word time stamps, but no other problems
# - 3.09 GB
# https://github.com/nyrahealth/CrisperWhisper
# https://huggingface.co/nyrahealth/faster_CrisperWhisper
CRISPER_WHISPER_MODEL = "nyrahealth/faster_CrisperWhisper"

# This model should be used when using OpenAI API
OPENAI_WHISPER_MODEL = "whisper-1"


def model_size_and_audio_lang_to_model(model_size: ModelSize, audio_lang: str | None = None) -> str:
    """
    Base whisper has a lot of hallucinations, so don't use it just by itself.
    """
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
            # Don't use turbo version if you can, it has some degradation:
            #   https://github.com/SYSTRAN/faster-whisper/issues/1025#issuecomment-2387828445
            #   "Across languages, the turbo model performs similarly to large-v2,
            #   though it shows larger degradation on some languages like Thai and Cantonese."
            return "Systran/faster-whisper-large-v3"

    raise ValueError("No matching model found")
