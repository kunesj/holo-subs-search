#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, Any, Self

from .youtube_record import YoutubeRecord

if TYPE_CHECKING:
    from .storage import Storage

_logger = logging.getLogger(__name__)
HOLODEX_JSON = "holodex.json"


class HolodexRecord(YoutubeRecord, abc.ABC):
    # Fields / Properties

    @property
    def holodex_info(self) -> dict[str, Any] | None:
        return self.load_json_file(HOLODEX_JSON)

    @holodex_info.setter
    def holodex_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Holodex info for %r ID=%s", self.model_name, self.id)
        else:
            _logger.info("Saving Holodex info for %r ID=%s", self.model_name, self.id)
        self.save_json_file(HOLODEX_JSON, value)

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
