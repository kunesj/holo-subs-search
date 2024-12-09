from __future__ import annotations

import abc
import logging
import pathlib
from typing import TYPE_CHECKING, Any, Callable, ClassVar, TypeVar

from .mixins.files_mixin import FilesMixin
from .mixins.filterable_mixin import FilterableMixin, FilterPart
from .mixins.metadata_mixin import MetadataMixin

if TYPE_CHECKING:
    from .storage import Storage

T = TypeVar("T")

_logger = logging.getLogger(__name__)


class Record(MetadataMixin, FilesMixin, FilterableMixin, abc.ABC):
    model_name: ClassVar[str]
    id: str  # annotation to make it filterable

    def __init__(self, *, storage: Storage, id: str) -> None:
        super().__init__()
        self.storage = storage
        self.id = id

    def __str__(self) -> str:
        return repr(self)

    def __repr__(self) -> str:
        return f"{self.model_name}[{self.id}]"

    # Fields / Properties

    @property
    def model_path(self) -> pathlib.Path:
        return self.storage.path / self.model_name

    @property
    def record_path(self) -> pathlib.Path:
        return self.model_path / self.id

    @property
    def files_path(self) -> pathlib.Path:
        """Implemented"""
        return self.record_path

    # Methods

    def exists(self) -> bool:
        return self.record_path.exists() and self.record_path.is_dir() and self.metadata is not None

    def create(self, metadata: dict[str, Any]) -> None:
        if self.exists():
            raise ValueError("Already exists")

        self.model_path.mkdir(parents=True, exist_ok=True)
        self.record_path.mkdir(parents=True, exist_ok=True)
        self.metadata = metadata

    @classmethod
    def build_filter(cls: type[T], *parts: FilterPart) -> Callable[[T], bool]:
        return super().build_filter(FilterPart(name="model_name", operator="eq", value=cls.model_name), *parts)
