from __future__ import annotations

import logging
import os
import pathlib
import weakref
from typing import Any, Callable, Iterator, Literal, TypeVar

from .. import __version__
from . import migrations
from .channel import ChannelRecord
from .mixins.metadata_mixin import MetadataMixin
from .record import Record
from .video import VideoRecord

RecordT = TypeVar("RecordT", bound=Record)
GitPrivacyType = Literal["private", "public"]

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

    @property
    def git_privacy(self) -> GitPrivacyType:
        return self.metadata["git_privacy"]

    @git_privacy.setter
    def git_privacy(self, value: GitPrivacyType) -> None:
        self.metadata = dict(self.metadata, git_privacy=value)

    @classmethod
    def build_metadata(cls, git_privacy: GitPrivacyType = "private", **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"version": __version__, "git_privacy": git_privacy}

    def migrate(self) -> None:
        visited = set()
        while True:
            version = self.metadata["version"]
            if version in visited:
                raise ValueError("Version migration already done! Cyclic migration?", version)
            visited.add(version)

            self.metadata = migrations.migrate_0_1_0(self.path, self.metadata)
            self.metadata = migrations.migrate_0_2_0(self.path, self.metadata)
            self.metadata = migrations.migrate_0_3_0(self.path, self.metadata)
            self.metadata = migrations.migrate_0_4_0(self.path, self.metadata)
            self.metadata = migrations.migrate_0_5_0(self.path, self.metadata)
            self.metadata = migrations.migrate_0_6_0(self.path, self.metadata)

            if version == self.metadata["version"]:
                break

        if self.metadata["version"] != __version__:
            raise ValueError("Storage was not migrated to current version!", self.metadata["version"], __version__)

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
