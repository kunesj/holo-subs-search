from __future__ import annotations

import abc
import logging
import os
import pathlib
from typing import Callable, Iterator

from ..content_item import CONTENT_ITEM_TYPES, AudioItem, BaseItem, ContentItemType, DiarizationItem, SubtitleItem
from .files_mixin import FilesMixin

_logger = logging.getLogger(__name__)


class ContentMixin(FilesMixin, abc.ABC):
    # Properties

    @property
    def content_path(self) -> pathlib.Path:
        return self.files_path / "content/"

    @property
    def audio_sources(self) -> frozenset[str]:
        return frozenset(x.source for x in self.list_content(AudioItem.build_filter()))

    @property
    def diarization_sources(self) -> frozenset[str]:
        return frozenset(x.source for x in self.list_content(DiarizationItem.build_filter()))

    @property
    def subtitle_sources(self) -> frozenset[str]:
        return frozenset(x.source for x in self.list_content(SubtitleItem.build_filter()))

    @property
    def subtitle_langs(self) -> frozenset[str]:
        return frozenset(x.lang for x in self.list_content(SubtitleItem.build_filter()))

    # Methods

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
