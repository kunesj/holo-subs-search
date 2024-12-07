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
    def subtitle_file(self) -> str:
        return self.metadata["subtitle_file"]

    @property
    def subtitle_path(self) -> pathlib.Path:
        return self.files_path / self.subtitle_file

    # Transcription properties

    @property
    def whisper_audio(self) -> str | None:
        return self.metadata.get("whisper_audio", None)

    @whisper_audio.setter
    def whisper_audio(self, value: str | None) -> None:
        self.metadata = dict(self.metadata, whisper_audio=value)

    @property
    def whisper_model(self) -> str | None:
        return self.metadata.get("whisper_model", None)

    @whisper_model.setter
    def whisper_model(self, value: str | None) -> None:
        self.metadata = dict(self.metadata, whisper_model=value)

    # Methods

    @classmethod
    def build_metadata(
        cls,
        *,
        source: str,
        lang: str,
        subtitle_file: str,
        whisper_audio: str | None = None,
        whisper_model: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {
            "source": source,
            "lang": lang,
            "subtitle_file": subtitle_file,
            "whisper_audio": whisper_audio,
            "whisper_model": whisper_model,
        }
