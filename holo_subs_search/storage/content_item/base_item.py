from __future__ import annotations

import logging
import os
import pathlib
import re
from typing import Any, Callable, ClassVar, TypeVar

from ..mixins.files_mixin import FilesMixin
from ..mixins.filterable_mixin import FilterableMixin, FilterPart
from ..mixins.flags_mixin import FlagsMixin
from ..mixins.metadata_mixin import MetadataMixin

T = TypeVar("T")

_logger = logging.getLogger(__name__)


class BaseItem(FlagsMixin, MetadataMixin, FilesMixin, FilterableMixin):
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
    def content_id(self) -> str:
        return os.path.basename(self.path)

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

    @classmethod
    def build_filter(cls: type[T], *parts: FilterPart) -> Callable[[T], bool]:
        return super().build_filter(FilterPart(name="item_type", operator="eq", value=cls.item_type), *parts)

    @classmethod
    def build_content_id(cls, *parts: Any) -> str:
        if not parts:
            raise ValueError("At least one content ID part is required")

        parts = [str(x) for x in [cls.item_type, *parts]]
        parts = [re.sub(r"[^a-zA-Z0-9\-]+", "-", x) for x in parts]

        return "_".join(parts)
