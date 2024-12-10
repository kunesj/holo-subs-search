from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

from ...utils import json_dumps

_logger = logging.getLogger(__name__)


def migrate_0_1_0(storage_path: pathlib.Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata["version"] != "0.1.0":
        return metadata
    _logger.info("Storage migration from version 0.1.0")

    # channel

    model_path = storage_path / "channel"
    with os.scandir(model_path) as it:
        for entry in it:
            record_path = model_path / entry.name

            # convert metadata

            metadata_path = record_path / "metadata.json"
            if metadata_path.exists() and metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text())
                metadata["flags"] = set()

                if not metadata.pop("refresh_holodex_info", True):
                    metadata["flags"].add("holodex-preserve")

                if not metadata.pop("refresh_videos", True):
                    metadata["flags"].add("mentions-only")

                metadata_path.write_text(json_dumps(metadata))

    # video

    model_path = storage_path / "video"
    with os.scandir(model_path) as it:
        for entry in it:
            record_path = model_path / entry.name

            # convert metadata

            metadata_path = record_path / "metadata.json"
            if metadata_path.exists() and metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text())

                # flags

                metadata["flags"] = set()

                if metadata.pop("members_only", False):
                    metadata["flags"].add("youtube-membership")

                # youtube_subtitles

                youtube_subtitles = {}

                for lang in metadata.pop("skip_subtitles", []):
                    if lang == "all":
                        continue  # private or unavailable
                    youtube_subtitles[lang] = "missing"

                if youtube_subtitles:
                    metadata["youtube_subtitles"] = youtube_subtitles

                metadata_path.write_text(json_dumps(metadata))

            # convert subtitles to content

            subtitles_path = record_path / "subtitles/"
            if subtitles_path.exists():
                content_root_path = record_path / "content/"
                content_root_path.mkdir(parents=True, exist_ok=True)

                with os.scandir(subtitles_path) as sub_it:
                    for sub_entry in sub_it:
                        source, lang, ext = sub_entry.name.split(".")
                        content_id = f"{source}-subtitles-{lang}"

                        src_path = subtitles_path / sub_entry.name
                        content_path = content_root_path / content_id
                        content_path.mkdir(parents=True, exist_ok=True)

                        dest_srt_path = content_path / sub_entry.name
                        dest_srt_path.write_bytes(src_path.read_bytes())

                        dest_meta_path = content_path / "metadata.json"
                        dest_meta_path.write_text(
                            json_dumps(
                                {
                                    "item_type": "subtitle",
                                    "source": source,
                                    "lang": lang,
                                    "subtitle_file": sub_entry.name,
                                }
                            )
                        )

                        src_path.unlink()

                subtitles_path.rmdir()

            # convert .gitignore

            gitignore_path = record_path / ".gitignore"
            if gitignore_path.exists():
                gitignore_path.write_text(gitignore_path.read_text().replace("/subtitles\n", "/content\n"))

    return dict(metadata, version="0.2.0")
