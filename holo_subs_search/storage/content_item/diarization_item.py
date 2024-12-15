from __future__ import annotations

import logging
from typing import Any, ClassVar

from ...diarization import Diarization
from .base_item import BaseItem

_logger = logging.getLogger(__name__)


class DiarizationItem(BaseItem):
    item_type = "diarization"
    DIARIZATION_JSON: ClassVar[str] = "diarization.json"

    # Properties

    @property
    def audio_id(self) -> str | None:
        return self.metadata.get("audio_id", None)

    @property
    def checkpoint(self) -> str:
        dia = self.load_diarization()
        return dia.checkpoint if dia else None

    @property
    def segmentation_model(self) -> str | None:
        dia = self.load_diarization()
        return dia.segmentation_model if dia else None

    @property
    def embedding_model(self) -> str | None:
        dia = self.load_diarization()
        return dia.embedding_model if dia else None

    # Methods

    @classmethod
    def build_metadata(cls, *, audio_id: str | None = None, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"audio_id": audio_id}

    def load_diarization(self) -> Diarization | None:
        raw = self.load_json_file(self.DIARIZATION_JSON)
        return None if raw is None else Diarization.model_validate(raw)

    def save_diarization(self, value: Diarization | None) -> None:
        raw = None if value is None else value.model_dump(mode="json")
        self.save_json_file(self.DIARIZATION_JSON, raw)
