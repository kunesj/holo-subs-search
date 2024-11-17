#!/usr/bin/env python3.11

from __future__ import annotations

import logging
import os
import pathlib
import weakref
from typing import Iterator, TypeVar

from .channel_record import ChannelRecord
from .record import Record
from .video_record import VideoRecord

RecordT = TypeVar("RecordT", bound=Record)

_logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, *, path: pathlib.Path) -> None:
        self._record_cache = weakref.WeakValueDictionary()
        self.path = path
        self.path.mkdir(exist_ok=True)

    # Generic Records

    def list_records(self, model: type[RecordT]) -> Iterator[RecordT]:
        table_path = self.path / model.model_name
        if not table_path.exists():
            return

        with os.scandir(table_path) as it:
            for entry in it:
                if record := self.get_record(model, entry.name):
                    yield record

    def get_record(self, model: type[RecordT], id_: str) -> RecordT | None:
        key = (model.model_name, id_)

        if key in self._record_cache:
            return self._record_cache[key]

        record = model(storage=self, id=id_)
        if record.exists():
            self._record_cache[key] = record
            return record

        return None

    # Channels

    def list_channels(self) -> Iterator[ChannelRecord]:
        for record in self.list_records(ChannelRecord):
            yield record

    def get_channel(self, id_: str) -> ChannelRecord | None:
        return self.get_record(ChannelRecord, id_)

    # Videos

    def list_videos(self) -> Iterator[VideoRecord]:
        for record in self.list_records(VideoRecord):
            yield record

    def get_video(self, id_: str) -> VideoRecord | None:
        return self.get_record(VideoRecord, id_)
