from __future__ import annotations

import logging
import pathlib
from typing import Any

from ...utils import get_checksum
from .base_item import BaseItem

_logger = logging.getLogger(__name__)


class AudioItem(BaseItem):
    item_type = "audio"

    @property
    def source(self) -> str:
        return self.metadata["source"]

    @property
    def audio_file(self) -> str:
        return self.metadata["audio_file"]

    @property
    def audio_path(self) -> pathlib.Path:
        return self.files_path / self.audio_file

    @property
    def audio_checksum(self) -> str:
        return get_checksum(self.audio_path.read_bytes())

    @classmethod
    def build_metadata(cls, *, source: str, audio_file: str, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"source": source, "audio_file": audio_file}
