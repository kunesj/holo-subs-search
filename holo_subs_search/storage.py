#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import json
import logging
import os
import pathlib
import weakref
from typing import Any, ClassVar, Iterator, Self, TypeVar

from holodex.model.channel import Channel as HolodexChannel
from holodex.model.channel_video import ChannelVideoInfo as HolodexChannelVideoInfo
from holodex.model.channels import LiteChannel as HolodexLiteChannel

_logger = logging.getLogger(__name__)

DATA_PATH = (pathlib.Path(os.path.dirname(__file__)) / "../data/").absolute()
METADATA_JSON = "metadata.json"
HOLODEX_JSON = "holodex.json"
YOUTUBE_JSON = "youtube.json"


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


class _Record(abc.ABC):
    model_name: ClassVar[str]
    _cache: dict

    def __init__(self, *, storage: Storage, id: str) -> None:
        self._cache = {}
        self.storage = storage
        self.id = id

    @property
    def model_path(self) -> pathlib.Path:
        return self.storage.path / self.model_name

    @property
    def record_path(self) -> pathlib.Path:
        return self.model_path / self.id

    def exists(self) -> bool:
        return self.record_path.exists() and self.record_path.is_dir() and self.metadata is not None

    def create(self, **kwargs) -> None:
        if self.exists():
            raise ValueError("Already exists")

        self.model_path.mkdir(exist_ok=True)
        self.record_path.mkdir(exist_ok=True)
        self.save_json_file(METADATA_JSON, kwargs)

    # Metadata

    @property
    def metadata(self) -> dict[str, Any] | None:
        return self.load_json_file(METADATA_JSON)

    # Files

    def load_text_file(self, name: str, from_cache: bool = True) -> str | None:
        key = ("text", name)

        if key not in self._cache or not from_cache:
            path = self.record_path / name
            if path.exists() and path.is_file():
                self._cache[key] = path.read_text()

        return self._cache.get(key)

    def load_json_file(self, name: str, from_cache: bool = True) -> dict[str, Any] | None:
        key = ("json", name)

        if key not in self._cache or not from_cache:
            value = self.load_text_file(name, from_cache=False)
            if value is not None:
                self._cache[key] = json.loads(value)

        return self._cache.get(key)

    def save_text_file(self, name: str, value: str | None) -> None:
        key = ("text", name)
        self._cache.pop(key, None)

        if not self.record_path.exists():
            raise ValueError("Record directory does not exist! Virtual record?")

        path = self.record_path / name
        if value is None:
            path.unlink(missing_ok=True)
        elif isinstance(value, str):
            path.write_text(value)
        else:
            raise TypeError(value)

        if value is not None:
            self._cache[key] = value

    def save_json_file(self, name: str, value: dict[str, Any] | None) -> None:
        key = ("json", name)
        self._cache.pop(key, None)

        if isinstance(value, dict):
            value = json.dumps(value)
        self.save_text_file(name, value)

        if value is not None:
            self._cache[key] = value


class _YoutubeRecord(_Record, abc.ABC):
    @property
    def youtube_info(self) -> dict[str, Any] | None:
        return self.load_json_file(YOUTUBE_JSON)

    @youtube_info.setter
    def youtube_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Youtube info for %r ID=%s", self.model_name, self.id)
        else:
            _logger.info("Setting Youtube info for %r ID=%s", self.model_name, self.id)
        self.save_json_file(YOUTUBE_JSON, value)

    @property
    def youtube_id(self) -> str | None:
        return self.youtube_info.get("id") if self.youtube_info else None


class _HolodexRecord(_YoutubeRecord, abc.ABC):
    @property
    def holodex_info(self) -> dict[str, Any] | None:
        return self.load_json_file(HOLODEX_JSON)

    @holodex_info.setter
    def holodex_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing Holodex info for %r ID=%s", self.model_name, self.id)
        else:
            _logger.info("Setting Holodex info for %r ID=%s", self.model_name, self.id)
        self.save_json_file(HOLODEX_JSON, value)

    @property
    def holodex_id(self) -> str | None:
        if self.holodex_info:
            return self.holodex_info.get("id")
        elif self.youtube_info:
            return self.youtube_info.get("id")
        return None

    @property
    def youtube_id(self) -> str | None:
        if self.youtube_info:
            return self.youtube_info.get("id")
        elif self.holodex_info:
            return self.holodex_info.get("id")
        return None

    @classmethod
    def from_holodex_id(cls: type[Self], *, storage: Storage, id: str) -> Self:
        # id == holodex_id right now
        return cls(storage=storage, id=id)


RecordT = TypeVar("RecordT", bound=_Record)


class ChannelRecord(_HolodexRecord):
    model_name = "channel"

    @property
    def refresh_holodex_info(self) -> str:
        """False if this channel should be skipped when refreshing channel info"""
        return self.metadata["refresh_holodex_info"]

    @property
    def refresh_videos(self) -> str:
        """False if this channel should be skipped when refreshing video list"""
        return self.metadata["refresh_videos"]

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
    ) -> Self:
        holodex_info = json.loads(json.dumps(value._response))

        record = cls.from_holodex_id(storage=storage, id=value.id)
        if not record.exists():
            record.create(**(default_metadata or {}))

        record.holodex_info = holodex_info
        return record

    # Videos

    def list_videos(self) -> Iterator[VideoRecord]:
        for record in self.storage.list_videos():
            if self.id == record.channel_id:
                yield record


class VideoRecord(_HolodexRecord):
    model_name = "video"

    @property
    def channel_id(self) -> str:
        return self.metadata["channel_id"]

    def create(self, channel_id: str, **kwargs) -> None:
        return super().create(channel_id=channel_id, **kwargs)

    @classmethod
    def from_holodex(
        cls: type[Self],
        *,
        storage: Storage,
        value: HolodexChannelVideoInfo,
        default_metadata: dict[str, Any] | None = None,
    ) -> Self:
        holodex_info = json.loads(json.dumps(value._response))

        record = cls.from_holodex_id(storage=storage, id=value.id)
        if not record.exists():
            channel = ChannelRecord.from_holodex_id(storage=storage, id=value.channel.id)
            if not channel.exists():
                channel = ChannelRecord.from_holodex(
                    storage=storage, value=value.channel, default_metadata={"refresh_videos": False}
                )

            default_metadata = (default_metadata or {}) | {"channel_id": channel.id}
            record.create(**default_metadata)

        record.holodex_info = holodex_info
        return record
