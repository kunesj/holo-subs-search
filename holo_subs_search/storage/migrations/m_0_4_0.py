from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

_logger = logging.getLogger(__name__)


def migrate_0_4_0(storage_path: pathlib.Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata["version"] != "0.4.0":
        return metadata
    _logger.info("Storage migration from version 0.4.0")

    video_table_p = storage_path / "video"
    if video_table_p.exists() and video_table_p.is_dir():
        _migrate_0_4_0__video_table(video_table_p)

    return dict(metadata, version="0.5.0")


def _migrate_0_4_0__video_table(video_table_p: pathlib.Path) -> None:
    with os.scandir(video_table_p) as it:
        for entry in it:
            video_entry_p = video_table_p / entry.name
            if video_entry_p.exists() and video_entry_p.is_dir() and (video_entry_p / "metadata.json").exists():
                _migrate_0_4_0__video(video_entry_p)


def _migrate_0_4_0__video(video_p: pathlib.Path) -> None:
    content_p = video_p / "content"
    if content_p.exists() and content_p.is_dir():
        with os.scandir(content_p) as it:
            for entry in it:
                item_metadata_p = content_p / entry.name / "metadata.json"
                if item_metadata_p.exists() and item_metadata_p.is_file():
                    metadata = json.loads(item_metadata_p.read_text())
                    if metadata.get("item_type") == "subtitle":
                        metadata["langs"] = [metadata["lang"]]
                    item_metadata_p.write_text(json.dumps(metadata, sort_keys=True))
