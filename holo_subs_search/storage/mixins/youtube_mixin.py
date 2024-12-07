from __future__ import annotations

import abc
import logging
from types import MappingProxyType
from typing import Any, ClassVar

from .files_mixin import FilesMixin

_logger = logging.getLogger(__name__)


class YoutubeMixin(FilesMixin, abc.ABC):
    YOUTUBE_JSON: ClassVar[str] = "youtube.json"

    # Fields / Properties

    @property
    def youtube_info(self) -> MappingProxyType[str, Any] | None:
        raw = self.load_json_file(self.YOUTUBE_JSON)
        return None if raw is None else MappingProxyType(raw)

    @youtube_info.setter
    def youtube_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Youtube info for %r", self)
        else:
            _logger.info("Saving Youtube info for %r", self)
        self.save_json_file(self.YOUTUBE_JSON, value)

    @property
    def youtube_id(self) -> str | None:
        return self.youtube_info.get("id") if self.youtube_info else None

    @property
    @abc.abstractmethod
    def youtube_url(self) -> str | None:
        raise NotImplementedError()
