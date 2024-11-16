#!/usr/bin/env python3.11

import os
import tempfile
from typing import Any, Iterator, Sequence

from yt_dlp import YoutubeDL


def get_video_params(download_path: str, langs: list[str]) -> dict[str, Any]:
    return {
        "skip_download": True,
        # download automatic subtitles and convert them to SRT format
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": langs,
        "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"}],
        # download info.json
        "writeinfojson": True,
        "clean_infojson": True,
        # save paths and names
        "paths": {
            "subtitle": download_path,
            "infojson": download_path,
        },
        "outtmpl": {
            # .en.srt suffix is added automatically
            "subtitle": "%(id)s.%(ext)s",
            # .info.json suffix is added automatically
            "infojson": "%(id)s",
        },
    }


def download_video_info_and_subtitles(video_ids: Sequence[str], langs: list[str]) -> Iterator[tuple[str, str, str]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        # download all new files

        with YoutubeDL(params=get_video_params(download_path=tmpdir, langs=langs)) as ydl:
            error_code = ydl.download([f"https://www.youtube.com/watch?v={id_}" for id_ in video_ids])
            if error_code != 0:
                raise Exception("yt-dlp download failed!")

        with os.scandir(tmpdir) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                video_id, name = entry.name.split(".", maxsplit=1)
                yield video_id, name, entry.path
