#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import logging
from typing import Any

from .record import Record

_logger = logging.getLogger(__name__)
YOUTUBE_JSON = "youtube.json"


class YoutubeRecord(Record, abc.ABC):
    # Fields / Properties

    @property
    def youtube_info(self) -> dict[str, Any] | None:
        return self.load_json_file(YOUTUBE_JSON)

    @youtube_info.setter
    def youtube_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Youtube info for %r ID=%s", self.model_name, self.id)
        else:
            _logger.info("Saving Youtube info for %r ID=%s", self.model_name, self.id)
        self.save_json_file(YOUTUBE_JSON, value)

    @property
    def youtube_id(self) -> str | None:
        return self.youtube_info.get("id") if self.youtube_info else None

    @property
    @abc.abstractmethod
    def youtube_url(self) -> str | None:
        raise NotImplementedError()
