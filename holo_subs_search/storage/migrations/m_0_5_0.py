from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

_logger = logging.getLogger(__name__)


def migrate_0_5_0(storage_path: pathlib.Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata["version"] != "0.5.0":
        return metadata
    _logger.info("Storage migration from version 0.5.0")

    video_table_p = storage_path / "video"
    if video_table_p.exists() and video_table_p.is_dir():
        _migrate_0_5_0__video_table(video_table_p)

    return dict(metadata, version="0.6.0")


def _migrate_0_5_0__video_table(video_table_p: pathlib.Path) -> None:
    with os.scandir(video_table_p) as it:
        for entry in it:
            video_entry_p = video_table_p / entry.name
            if video_entry_p.exists() and video_entry_p.is_dir() and (video_entry_p / "metadata.json").exists():
                _migrate_0_5_0__video(video_entry_p)


def _migrate_0_5_0__video(video_p: pathlib.Path) -> None:
    content_p = video_p / "content"
    if content_p.exists() and content_p.is_dir():
        with os.scandir(content_p) as it:
            for entry in it:
                item_metadata_p = content_p / entry.name / "metadata.json"
                if item_metadata_p.exists() and item_metadata_p.is_file():
                    metadata = json.loads(item_metadata_p.read_text())
                    if metadata.get("item_type") != "diarization":
                        continue

                item_dia_p = content_p / entry.name / "diarization.json"
                if item_dia_p.exists() and item_dia_p.is_file():
                    dia = json.loads(item_dia_p.read_text())
                    if "checkpoint" in dia:
                        continue  # already migrated

                    checkpoint = dia.pop("diarization_model", "unknown")
                    if checkpoint == "pyannote/speaker-diarization-3.1":
                        segmentation_model = "pyannote/segmentation-3.0"
                        segmentation_batch_size = 32
                        embedding_model = "pyannote/wespeaker-voxceleb-resnet34-LM"
                        embedding_batch_size = 32
                        embedding_exclude_overlap = True
                        clustering = "AgglomerativeClustering"
                    else:
                        segmentation_model = None
                        segmentation_batch_size = -1
                        embedding_model = None
                        embedding_batch_size = -1
                        embedding_exclude_overlap = False
                        clustering = "unknown"

                    if _value := dia.pop("embedding_model", None):
                        # it's more important that we save the model used for the speaker embeddings,
                        # than the model used during the diarization
                        embedding_model = _value

                    dia |= {
                        # config
                        "checkpoint": checkpoint,
                        "segmentation_model": segmentation_model,
                        "segmentation_batch_size": segmentation_batch_size,
                        "embedding_model": embedding_model,
                        "embedding_batch_size": embedding_batch_size,
                        "embedding_exclude_overlap": embedding_exclude_overlap,
                        "clustering": clustering,
                        # results
                        "segments": dia.pop("diarization"),
                    }

                    item_dia_p.write_text(json.dumps(dia, sort_keys=True))
