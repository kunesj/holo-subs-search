#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Self

from .youtube_mixin import YoutubeMixin

if TYPE_CHECKING:
    from ..storage import Storage

_logger = logging.getLogger(__name__)


class HolodexMixin(YoutubeMixin, abc.ABC):
    HOLODEX_JSON: ClassVar[str] = "holodex.json"

    # Fields / Properties

    @property
    def holodex_info(self) -> MappingProxyType[str, Any] | None:
        raw = self.load_json_file(self.HOLODEX_JSON)
        return None if raw is None else MappingProxyType(raw)

    @holodex_info.setter
    def holodex_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Holodex info for %r", self)
        else:
            _logger.info("Saving Holodex info for %r", self)
        self.save_json_file(self.HOLODEX_JSON, value)

    @property
    def holodex_id(self) -> str | None:
        if self.holodex_info:
            return self.holodex_info.get("id")
        elif self.youtube_info:
            return self.youtube_info.get("id")
        return None

    @property
    @abc.abstractmethod
    def holodex_url(self) -> str | None:
        raise NotImplementedError()

    @property
    def youtube_id(self) -> str | None:
        if self.youtube_info:
            return self.youtube_info.get("id")
        elif self.holodex_info:
            return self.holodex_info.get("id")
        return None

    # Methods

    @classmethod
    def from_holodex_id(cls: type[Self], *, storage: Storage, id: str) -> Self:
        # id == holodex_id right now
        return cls(storage=storage, id=id)
