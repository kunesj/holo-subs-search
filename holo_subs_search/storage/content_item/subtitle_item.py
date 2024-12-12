from __future__ import annotations

import logging
import pathlib
from typing import Any

from .base_item import BaseItem

_logger = logging.getLogger(__name__)


class SubtitleItem(BaseItem):
    item_type = "subtitle"

    # Properties

    @property
    def source(self) -> str:
        return self.metadata["source"]

    @property
    def lang(self) -> str:
        return self.metadata["lang"]

    @property
    def langs(self) -> frozenset[str]:
        """All languages contained in the file"""
        return frozenset(self.metadata["langs"])

    @property
    def subtitle_file(self) -> str:
        return self.metadata["subtitle_file"]

    @property
    def subtitle_path(self) -> pathlib.Path:
        return self.files_path / self.subtitle_file

    # Transcription properties

    @property
    def audio_id(self) -> str | None:
        return self.metadata.get("audio_id", None)

    @property
    def diarization_id(self) -> str | None:
        return self.metadata.get("diarization_id", None)

    @property
    def whisper_model(self) -> str | None:
        return self.metadata.get("whisper_model", None)

    # Methods

    @classmethod
    def build_metadata(
        cls,
        *,
        source: str,
        lang: str,
        langs: set[str],
        subtitle_file: str,
        audio_id: str | None = None,
        diarization_id: str | None = None,
        whisper_model: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {
            "source": source,
            "lang": lang,
            "langs": langs,
            "subtitle_file": subtitle_file,
            "audio_id": audio_id,
            "diarization_id": diarization_id,
            "whisper_model": whisper_model,
        }
