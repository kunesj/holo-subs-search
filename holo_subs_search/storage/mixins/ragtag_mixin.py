from __future__ import annotations

import abc
import logging
from types import MappingProxyType
from typing import Any, ClassVar

from .files_mixin import FilesMixin

_logger = logging.getLogger(__name__)


class RagtagMixin(FilesMixin, abc.ABC):
    RAGTAG_JSON: ClassVar[str] = "ragtag.json"

    # Fields / Properties

    @property
    def ragtag_info(self) -> MappingProxyType[str, Any] | None:
        raw = self.load_json_file(self.RAGTAG_JSON)
        return None if raw is None else MappingProxyType(raw)

    @ragtag_info.setter
    def ragtag_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Ragtag info for %r", self)
        else:
            _logger.info("Saving Ragtag info for %r", self)
        self.save_json_file(self.RAGTAG_JSON, value)
