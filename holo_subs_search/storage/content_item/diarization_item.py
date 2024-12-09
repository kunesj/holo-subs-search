from __future__ import annotations

import logging
from typing import Any, ClassVar

from ...diarization import Diarization
from .base_item import BaseItem

_logger = logging.getLogger(__name__)


class DiarizationItem(BaseItem):
    item_type = "diarization"
    DIARIZATION_JSON: ClassVar[str] = "diarization.json"

    @property
    def source(self) -> str:
        return self.metadata["source"]

    @property
    def audio_id(self) -> str | None:
        return self.metadata.get("audio_id", None)

    @property
    def diarization(self) -> Diarization | None:
        raw = self.load_json_file(self.DIARIZATION_JSON)
        return None if raw is None else Diarization.model_validate(raw)

    @diarization.setter
    def diarization(self, value: Diarization) -> None:
        self.save_json_file(self.DIARIZATION_JSON, value.model_dump(mode="json"))

    @property
    def diarization_model(self) -> str | None:
        return self.diarization.diarization_model if self.diarization else None

    @property
    def embedding_model(self) -> str | None:
        return self.diarization.embedding_model if self.diarization else None

    @classmethod
    def build_metadata(cls, *, source: str, audio_id: str | None = None, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"source": source, "audio_id": audio_id}
