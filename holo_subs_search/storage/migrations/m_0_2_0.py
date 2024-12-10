from __future__ import annotations

import logging
import pathlib
from typing import Any

_logger = logging.getLogger(__name__)


def migrate_0_2_0(storage_path: pathlib.Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata["version"] != "0.2.0":
        return metadata
    _logger.info("Storage migration from version 0.2.0")

    # storage format had only minor changes that should be compatible

    return dict(metadata, version="0.3.0")
