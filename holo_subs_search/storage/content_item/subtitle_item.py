from __future__ import annotations

import logging
import pathlib
from typing import Any

from .base_item import BaseItem

_logger = logging.getLogger(__name__)


class SubtitleItem(BaseItem):
    item_type = "subtitle"

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

    @property
    def whisper(self) -> dict[str, Any] | None:
        return self.metadata.get("whisper", None)

    @whisper.setter
    def whisper(self, value: dict[str, Any] | None) -> None:  # FIXME: audio checksum
        self.metadata = dict(self.metadata, whisper=value)

    @classmethod
    def build_metadata(
        cls, *, source: str, lang: str, subtitle_file: str, whisper: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {
            "source": source,
            "lang": lang,
            "subtitle_file": subtitle_file,
            "whisper": whisper,
        }
