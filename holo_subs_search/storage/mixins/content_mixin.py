from __future__ import annotations

import abc
import logging
import os
import pathlib
import typing
from typing import Any, Callable, ClassVar, Iterator

from .files_mixin import FilesMixin
from .flags_mixin import FlagsMixin
from .metadata_mixin import MetadataMixin

_logger = logging.getLogger(__name__)


class BaseItem(FlagsMixin, MetadataMixin, FilesMixin):
    item_type: ClassVar[str] = "base"

    def __init__(self, *, path: pathlib.Path) -> None:
        super().__init__()
        self.path = path

    def __str__(self) -> str:
        return repr(self)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}[{self.path}]"

    # Fields / Properties

    @property
    def files_path(self) -> pathlib.Path:
        """Implemented"""
        return self.path

    # Methods

    def exists(self) -> bool:
        return self.path.exists() and self.path.is_dir() and self.metadata is not None

    def create(self, metadata: dict[str, Any]) -> None:
        if self.exists():
            raise ValueError("Already exists")

        self.path.mkdir(parents=True, exist_ok=True)
        self.metadata = metadata

    @classmethod
    def build_metadata(cls, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"item_type": cls.item_type}


class SubtitleItem(BaseItem):
    item_type = "subtitle"

    @property
    def source(self) -> str:
        return self.metadata["source"]

    @property
    def lang(self) -> str:
        return self.metadata["lang"]

    @property
    def subtitle_file(self) -> str:
        return self.metadata["subtitle_file"]

    @property
    def subtitle_path(self) -> pathlib.Path:
        return self.files_path / self.subtitle_file

    @property
    def whisper(self) -> dict[str, Any] | None:
        return self.metadata.get("whisper", None)

    @whisper.setter
    def whisper(self, value: dict[str, Any] | None) -> None:
        self.metadata = dict(self.metadata, whisper=value)

    @classmethod
    def build_metadata(
        cls, *, source: str, lang: str, subtitle_file: str, whisper: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {
            "source": source,
            "lang": lang,
            "subtitle_file": subtitle_file,
            "whisper": whisper,
        }


class AudioItem(BaseItem):
    item_type = "audio"

    @property
    def source(self) -> str:
        return self.metadata["source"]

    @property
    def audio_file(self) -> str:
        return self.metadata["audio_file"]

    @property
    def audio_path(self) -> pathlib.Path:
        return self.files_path / self.audio_file

    @classmethod
    def build_metadata(cls, *, source: str, audio_file: str, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"source": source, "audio_file": audio_file}


ContentItemType = SubtitleItem | AudioItem
CONTENT_ITEM_TYPES = typing.get_args(ContentItemType)


class ContentMixin(FilesMixin, abc.ABC):
    @property
    def content_path(self) -> pathlib.Path:
        return self.files_path / "content/"

    def list_content(self, item_filter: Callable[[ContentItemType], bool] | None = None) -> Iterator[ContentItemType]:
        if not self.content_path.exists():
            return

        with os.scandir(self.content_path) as it:
            for entry in it:
                if entry.is_dir():
                    item = self.get_content(entry.name)
                    if item and (not item_filter or item_filter(item)):
                        yield item

    def get_content(self, id_: str) -> ContentItemType | None:
        path = self.content_path / id_

        # get item type

        base_item = BaseItem(path=path)
        if not base_item.exists():
            return None
        item_type = base_item.metadata["item_type"]

        # return content item object

        for item_cls in CONTENT_ITEM_TYPES:
            if item_cls.item_type == item_type:
                return item_cls(path=path)

        raise ValueError("Unexpected item type", item_type)
