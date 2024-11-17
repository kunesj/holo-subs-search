#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import json
import logging
import pathlib
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from .storage import Storage

_logger = logging.getLogger(__name__)
METADATA_JSON = "metadata.json"


class Record(abc.ABC):
    model_name: ClassVar[str]
    _cache: dict

    def __init__(self, *, storage: Storage, id: str) -> None:
        self._cache = {}
        self.storage = storage
        self.id = id

    # Fields / Properties

    @property
    def model_path(self) -> pathlib.Path:
        return self.storage.path / self.model_name

    @property
    def record_path(self) -> pathlib.Path:
        return self.model_path / self.id

    @property
    def metadata(self) -> dict[str, Any] | None:
        return self.load_json_file(METADATA_JSON)

    # Methods

    def exists(self) -> bool:
        return self.record_path.exists() and self.record_path.is_dir() and self.metadata is not None

    def create(self, **kwargs) -> None:
        if self.exists():
            raise ValueError("Already exists")

        self.model_path.mkdir(exist_ok=True)
        self.record_path.mkdir(exist_ok=True)
        self.save_json_file(METADATA_JSON, kwargs)

    # Files

    def load_text_file(self, name: str, from_cache: bool = True) -> str | None:
        key = ("text", name)

        if key not in self._cache or not from_cache:
            self._cache.pop(key, None)

            path = self.record_path / name
            if path.exists() and path.is_file():
                self._cache[key] = path.read_text()

        return self._cache.get(key)

    def load_json_file(self, name: str, from_cache: bool = True) -> dict[str, Any] | None:
        key = ("json", name)

        if key not in self._cache or not from_cache:
            self._cache.pop(key, None)

            value_text = self.load_text_file(name, from_cache=False)
            if value_text is not None:
                self._cache[key] = json.loads(value_text)

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

        if value is None:
            value_text = value
        elif isinstance(value, (dict, list)):
            value_text = json.dumps(value)
        else:
            raise TypeError(value)

        self.save_text_file(name, value_text)

        if value is not None:
            self._cache[key] = value
