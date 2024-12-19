from __future__ import annotations

import abc
import logging
from types import MappingProxyType
from typing import Any, ClassVar

from .files_mixin import FilesMixin

_logger = logging.getLogger(__name__)


class RubyRubyMixin(FilesMixin, abc.ABC):
    RUBYRUBY_JSON: ClassVar[str] = "rubyruby.json"

    # Fields / Properties

    @property
    def rubyruby_info(self) -> MappingProxyType[str, Any] | None:
        raw = self.load_json_file(self.RUBYRUBY_JSON)
        return None if raw is None else MappingProxyType(raw)

    @rubyruby_info.setter
    def rubyruby_info(self, value: dict[str, Any] | None) -> None:
        if value is None:
            _logger.info("Removing RubyRuby info for %r", self)
        else:
            _logger.info("Saving RubyRuby info for %r", self)
        self.save_json_file(self.RUBYRUBY_JSON, value)
