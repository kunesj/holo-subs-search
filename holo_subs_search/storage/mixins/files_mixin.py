#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import json
import logging
import pathlib
from typing import Any

from ...utils import json_dumps

_logger = logging.getLogger(__name__)


class FilesMixin(abc.ABC):
    _cache: dict

    def __init__(self, *args, **kwargs) -> None:
        self._cache = {}
        super().__init__(*args, **kwargs)

    @property
    @abc.abstractmethod
    def files_path(self) -> pathlib.Path:
        raise NotImplementedError()

    def load_text_file(self, name: str, from_cache: bool = True) -> str | None:
        key = ("text", name)

        if key not in self._cache or not from_cache:
            self._cache.pop(key, None)

            path = self.files_path / name
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

        self.files_path.mkdir(parents=True, exist_ok=True)

        path = self.files_path / name
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
        else:
            value_text = json_dumps(value)

        self.save_text_file(name, value_text)

        if value is not None:
            self._cache[key] = value
