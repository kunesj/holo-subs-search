#!/usr/bin/env python3.11

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
from typing import TYPE_CHECKING, Any, Iterator, Self

from holodex.model.channel_video import ChannelVideoInfo as HolodexChannelVideoInfo

from .holodex_record import HolodexRecord
from .record import METADATA_JSON

if TYPE_CHECKING:
    from .storage import Storage

_logger = logging.getLogger(__name__)


class VideoRecord(HolodexRecord):
    model_name = "video"

    # Fields / Properties

    @property
    def channel_id(self) -> str:
        return self.metadata["channel_id"]

    @property
    def skip_subtitles(self) -> list[str]:
        """Lists langs for which the subtitle fetch should be skipped. Use "all" to skip all."""
        return self.metadata.get("skip_subtitles", [])

    @skip_subtitles.setter
    def skip_subtitles(self, value: list[str]) -> None:
        metadata = dict(self.metadata, skip_subtitles=value)
        self.save_json_file(METADATA_JSON, metadata)

    @property
    def published_at(self) -> datetime.datetime | None:
        if self.holodex_info:
            return datetime.datetime.fromisoformat(self.holodex_info["published_at"])
        return None

    @property
    def members_only(self) -> bool:
        if "members_only" in self.metadata:
            return self.metadata["members_only"]
        elif self.holodex_info and (topic_id := self.holodex_info.get("topic_id")):
            return topic_id == "membersonly"
        return False

    @members_only.setter
    def members_only(self, value: bool) -> None:
        metadata = dict(self.metadata, members_only=value)
        self.save_json_file(METADATA_JSON, metadata)

    @property
    def title(self) -> str | None:
        if self.holodex_info and (title := self.holodex_info.get("title")):
            return title
        return None

    @property
    def youtube_url(self) -> str | None:
        """Implemented"""
        if self.youtube_id:
            return f"https://www.youtube.com/watch?v={self.youtube_id}"
        return None

    @property
    def holodex_url(self) -> str | None:
        """Implemented"""
        if self.holodex_id:
            return f"https://holodex.net/watch/{self.holodex_id}"
        return None

    @property
    def subtitles_path(self) -> pathlib.Path:
        return self.record_path / "subtitles/"

    # Methods

    def create(self, channel_id: str, skip_subtitles: list[str] | None = None, **kwargs) -> None:
        return super().create(channel_id=channel_id, skip_subtitles=skip_subtitles or [], **kwargs)

    @classmethod
    def from_holodex(
        cls: type[Self],
        *,
        storage: Storage,
        value: HolodexChannelVideoInfo,
        default_metadata: dict[str, Any] | None = None,
        update_holodex_info: bool = True,
    ) -> Self:
        holodex_info = json.loads(json.dumps(value._response))
        record = cls.from_holodex_id(storage=storage, id=value.id)

        if not record.exists():
            channel = ChannelRecord.from_holodex(
                storage=storage,
                value=value.channel,
                default_metadata={"refresh_videos": False},
                update_holodex_info=False,
            )
            default_metadata = (default_metadata or {}) | {"channel_id": channel.id}
            record.create(**default_metadata)
            record.holodex_info = holodex_info

        elif update_holodex_info or not record.holodex_info:
            record.holodex_info = holodex_info

        return record

    # Subtitles

    def list_subtitles(
        self,
        filter_source: list[str] | None = None,
        filter_lang: list[str] | None = None,
        filter_ext: list[str] | None = None,
    ) -> Iterator[str]:
        if not self.subtitles_path.exists():
            return
        elif filter_source is not None and not filter_source:
            return
        elif filter_lang is not None and not filter_lang:
            return
        elif filter_ext is not None and not filter_ext:
            return

        with os.scandir(self.subtitles_path) as it:
            for entry in it:
                if entry.is_file():
                    if entry.name.count(".") != 2:
                        _logger.error("Subtitles with invalid name skipped: %s", entry.name)
                        continue

                    source, lang, ext = entry.name.split(".")

                    if filter_source is not None and source not in filter_source:
                        continue
                    elif filter_lang is not None and lang not in filter_lang:
                        continue
                    elif filter_ext is not None and ext not in filter_ext:
                        continue

                    yield entry.name

    def save_subtitle(self, name: str, content: str | None) -> None:
        if name.count(".") != 2:
            raise ValueError("Name of subtitle format must be in `SOURCE-OR-TYPE.LANG.EXT` format", name)

        file_path = self.subtitles_path / name
        if content is None:
            if file_path.exists():
                file_path.unlink()
        else:
            self.subtitles_path.mkdir(exist_ok=True)
            file_path.write_text(content)

    def load_subtitle(self, name: str) -> str | None:
        file_path = self.subtitles_path / name
        return file_path.read_text() if file_path.exists() else None

    def update_gitignore(self) -> None:
        gitignore_path = self.record_path / ".gitignore"
        if self.members_only and not gitignore_path.exists():
            gitignore_path.write_text("/subtitles\n")
        elif not self.members_only and gitignore_path.exists():
            gitignore_path.unlink()


# Following imports must be at the end of file to prevent cyclic import error
# flake8: noqa: E402
from .channel_record import ChannelRecord
