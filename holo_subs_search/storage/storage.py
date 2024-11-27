#!/usr/bin/env python3.11

from __future__ import annotations

import json
import logging
import os
import pathlib
import weakref
from typing import Any, Callable, Iterator, TypeVar

from .. import __version__
from ..utils import json_dumps
from .channel import ChannelRecord
from .mixins.metadata_mixin import MetadataMixin
from .record import Record
from .video import VideoRecord

RecordT = TypeVar("RecordT", bound=Record)

_logger = logging.getLogger(__name__)


class Storage(MetadataMixin):
    def __init__(self, *, path: pathlib.Path) -> None:
        super().__init__()
        self._record_cache = weakref.WeakValueDictionary()
        self.path = path

        if not self.path.exists():
            self.path.mkdir(parents=True)
            self.metadata = self.build_metadata()

        if self.metadata is None:
            raise ValueError("Storage metadata.json is missing!")
        self.migrate()

    @property
    def files_path(self) -> pathlib.Path:
        return self.path

    @classmethod
    def build_metadata(cls, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"version": __version__}

    def migrate(self) -> None:
        visited = set()
        while True:
            version = self.metadata["version"]
            if version in visited:
                raise ValueError("Version migration already done! Cyclic migration?", version)
            visited.add(version)

            self.migrate_0_1_0()
            self.migrate_0_2_0()

            if version == self.metadata["version"]:
                break

        if self.metadata["version"] != __version__:
            raise ValueError("Storage was not migrated to current version!", self.metadata["version"], __version__)

    def migrate_0_1_0(self) -> None:
        if self.metadata["version"] != "0.1.0":
            return
        _logger.info("Storage migration from version 0.1.0")

        # channel

        model_path = self.path / "channel"
        with os.scandir(model_path) as it:
            for entry in it:
                record_path = model_path / entry.name

                # convert metadata

                metadata_path = record_path / "metadata.json"
                if metadata_path.exists() and metadata_path.is_file():
                    metadata = json.loads(metadata_path.read_text())
                    metadata["flags"] = set()

                    if not metadata.pop("refresh_holodex_info", True):
                        metadata["flags"].add("holodex-preserve")

                    if not metadata.pop("refresh_videos", True):
                        metadata["flags"].add("mentions-only")

                    metadata_path.write_text(json_dumps(metadata))

        # video

        model_path = self.path / "video"
        with os.scandir(model_path) as it:
            for entry in it:
                record_path = model_path / entry.name

                # convert metadata

                metadata_path = record_path / "metadata.json"
                if metadata_path.exists() and metadata_path.is_file():
                    metadata = json.loads(metadata_path.read_text())

                    # flags

                    metadata["flags"] = set()

                    if metadata.pop("members_only", False):
                        metadata["flags"].add("youtube-membership")

                    # youtube_subtitles

                    youtube_subtitles = {}

                    for lang in metadata.pop("skip_subtitles", []):
                        if lang == "all":
                            continue  # private or unavailable
                        youtube_subtitles[lang] = "missing"

                    if youtube_subtitles:
                        metadata["youtube_subtitles"] = youtube_subtitles

                    metadata_path.write_text(json_dumps(metadata))

                # convert subtitles to content

                subtitles_path = record_path / "subtitles/"
                if subtitles_path.exists():
                    content_root_path = record_path / "content/"
                    content_root_path.mkdir(parents=True, exist_ok=True)

                    with os.scandir(subtitles_path) as sub_it:
                        for sub_entry in sub_it:
                            source, lang, ext = sub_entry.name.split(".")
                            content_id = f"{source}-subtitles-{lang}"

                            src_path = subtitles_path / sub_entry.name
                            content_path = content_root_path / content_id
                            content_path.mkdir(parents=True, exist_ok=True)

                            dest_srt_path = content_path / sub_entry.name
                            dest_srt_path.write_bytes(src_path.read_bytes())

                            dest_meta_path = content_path / "metadata.json"
                            dest_meta_path.write_text(
                                json_dumps(
                                    {
                                        "item_type": "subtitle",
                                        "source": source,
                                        "lang": lang,
                                        "subtitle_file": sub_entry.name,
                                    }
                                )
                            )

                            src_path.unlink()

                    subtitles_path.rmdir()

                # convert .gitignore

                gitignore_path = record_path / ".gitignore"
                if gitignore_path.exists():
                    gitignore_path.write_text(gitignore_path.read_text().replace("/subtitles\n", "/content\n"))

        self.metadata = dict(self.metadata, version="0.2.0")

    def migrate_0_2_0(self) -> None:
        if self.metadata["version"] != "0.2.0":
            return
        _logger.info("Storage migration from version 0.2.0")

        # storage format had only minor changes that should be compatible

        self.metadata = dict(self.metadata, version="0.3.0")

    # Generic Records

    def list_records(
        self,
        model: type[RecordT],
        record_filter: Callable[[RecordT], bool] | None = None,
    ) -> Iterator[RecordT]:
        table_path = self.path / model.model_name
        if not table_path.exists():
            return

        with os.scandir(table_path) as it:
            for entry in it:
                record = self.get_record(model, entry.name)
                if record and (not record_filter or record_filter(record)):
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

    def list_channels(self, record_filter: Callable[[ChannelRecord], bool] | None = None) -> Iterator[ChannelRecord]:
        for record in self.list_records(ChannelRecord, record_filter=record_filter):
            yield record

    def get_channel(self, id_: str) -> ChannelRecord | None:
        return self.get_record(ChannelRecord, id_)

    # Videos

    def list_videos(self, record_filter: Callable[[VideoRecord], bool] | None = None) -> Iterator[VideoRecord]:
        for record in self.list_records(VideoRecord, record_filter=record_filter):
            yield record

    def get_video(self, id_: str) -> VideoRecord | None:
        return self.get_record(VideoRecord, id_)
