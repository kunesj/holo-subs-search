#!/usr/bin/env python3.11

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Iterator, Self

from holodex.model.channel import Channel as HolodexChannel
from holodex.model.channels import LiteChannel as HolodexLiteChannel

from .holodex_record import HolodexRecord

if TYPE_CHECKING:
    from .storage import Storage
    from .video_record import VideoRecord

_logger = logging.getLogger(__name__)


class ChannelRecord(HolodexRecord):
    model_name = "channel"

    # Fields / Properties

    @property
    def refresh_holodex_info(self) -> str:
        """False if this channel should be skipped when refreshing channel info"""
        return self.metadata["refresh_holodex_info"]

    @property
    def refresh_videos(self) -> str:
        """False if this channel should be skipped when refreshing video list"""
        return self.metadata["refresh_videos"]

    @property
    def youtube_url(self) -> str | None:
        """Implemented"""
        if self.youtube_id:
            return f"https://www.youtube.com/channel/{self.youtube_id}"
        return None

    @property
    def holodex_url(self) -> str | None:
        """Implemented"""
        if self.holodex_id:
            return f"https://holodex.net/channel/{self.holodex_id}"
        return None

    # Methods

    def create(
        self,
        refresh_holodex_info: bool = True,
        refresh_videos: bool = True,
        **kwargs,
    ) -> None:
        return super().create(refresh_holodex_info=refresh_holodex_info, refresh_videos=refresh_videos, **kwargs)

    @classmethod
    def from_holodex(
        cls: type[Self],
        *,
        storage: Storage,
        value: HolodexLiteChannel | HolodexChannel,
        default_metadata: dict[str, Any] | None = None,
        update_holodex_info: bool = True,
    ) -> Self:
        holodex_info = json.loads(json.dumps(value._response))
        record = cls.from_holodex_id(storage=storage, id=value.id)

        if not record.exists():
            record.create(**(default_metadata or {}))
            record.holodex_info = holodex_info

        elif update_holodex_info or not record.holodex_info:
            record.holodex_info = holodex_info

        return record

    # Videos

    def list_videos(self) -> Iterator[VideoRecord]:
        for record in self.storage.list_videos():
            if self.id == record.channel_id:
                yield record
