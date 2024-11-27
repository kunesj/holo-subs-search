#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import logging
from types import MappingProxyType
from typing import Any, ClassVar

from .files_mixin import FilesMixin

_logger = logging.getLogger(__name__)


class MetadataMixin(FilesMixin, abc.ABC):
    METADATA_JSON: ClassVar[str] = "metadata.json"

    @property
    def metadata(self) -> MappingProxyType[str, Any] | None:
        raw = self.load_json_file(self.METADATA_JSON)
        return None if raw is None else MappingProxyType(raw)

    @metadata.setter
    def metadata(self, value: dict[str, Any]) -> None:
        self.save_json_file(self.METADATA_JSON, value)

    @classmethod
    def build_metadata(cls, **kwargs) -> dict[str, Any]:
        if kwargs:
            raise ValueError("Extra metadata keys", kwargs)
        return {}
