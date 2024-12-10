from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from typing import Any

from ...utils import get_checksum

_logger = logging.getLogger(__name__)


def migrate_0_3_0(storage_path: pathlib.Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata["version"] != "0.3.0":
        return metadata
    _logger.info("Storage migration from version 0.3.0")

    # storage could only have "public" git_privacy in the past
    metadata = dict(metadata, git_privacy="public")

    # convert content_id of content items to new format
    video_table_p = storage_path / "video"
    if video_table_p.exists() and video_table_p.is_dir():
        _migrate_0_3_0__video_table(video_table_p)

    return dict(metadata, version="0.4.0")


def _migrate_0_3_0__video_table(video_table_p: pathlib.Path) -> None:
    with os.scandir(video_table_p) as it:
        for entry in it:
            video_entry_p = video_table_p / entry.name
            if video_entry_p.exists() and video_entry_p.is_dir() and (video_entry_p / "metadata.json").exists():
                _migrate_0_3_0__video(video_entry_p)


def _migrate_0_3_0__video(video_p: pathlib.Path) -> None:
    content_p = video_p / "content"
    if content_p.exists() and content_p.is_dir():
        with os.scandir(content_p) as it:
            for entry in it:
                item_p = content_p / entry.name
                if item_p.exists() and item_p.is_dir() and (item_p / "metadata.json").exists():
                    _migrate_0_3_0__content_item(item_p)


def _migrate_0_3_0__content_item(item_p: pathlib.Path) -> None:
    item_metadata = json.loads((item_p / "metadata.json").read_text())
    item_type = item_metadata["item_type"]

    if item_type == "subtitle":
        name = item_metadata["subtitle_file"]
        content = (item_p / name).read_bytes()
        new_content_id = _migrate_0_3_0__build_content_id(
            item_type, item_metadata["source"], get_checksum(content), name
        )
    elif item_type == "audio":
        name = item_metadata["audio_file"]
        content = (item_p / name).read_bytes()
        new_content_id = _migrate_0_3_0__build_content_id(
            item_type, item_metadata["source"], get_checksum(content), name
        )
    else:
        _logger.warning("Could not fix content_id of: %s", item_p)
        return

    new_item_p = item_p.parent / new_content_id
    _logger.info("Rename: %s -> %s", item_p, new_item_p)
    item_p.rename(new_item_p)


def _migrate_0_3_0__build_content_id(item_type: str, *parts: Any) -> str:
    if not parts:
        raise ValueError("At least one content ID part is required")

    parts = [str(x) for x in [item_type, *parts]]
    parts = [re.sub(r"[^a-zA-Z0-9\-]+", "-", x) for x in parts]

    return "_".join(parts)
