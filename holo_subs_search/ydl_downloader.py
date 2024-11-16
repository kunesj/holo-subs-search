#!/usr/bin/env python3.11

import os
import tempfile
from typing import Any, Iterator, Sequence

from yt_dlp import YoutubeDL


def get_video_params(download_path: str, langs: list[str], cookies_from_browser: str | None = None) -> dict[str, Any]:
    return {
        "skip_download": True,
        "cookiesfrombrowser": (cookies_from_browser,) if cookies_from_browser else None,
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
            "subtitle": "%(id)s.%(ext)s",  # ID.en.srt
            "infojson": "%(id)s",  # ID.info.json
        },
    }


def download_video_info_and_subtitles(
    video_ids: Sequence[str], langs: list[str], cookies_from_browser: str | None = None
) -> Iterator[tuple[str, str, str]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        # download all new files

        with YoutubeDL(
            params=get_video_params(download_path=tmpdir, langs=langs, cookies_from_browser=cookies_from_browser)
        ) as ydl:
            error_code = ydl.download([f"https://www.youtube.com/watch?v={id_}" for id_ in video_ids])
            if error_code != 0:
                raise Exception("yt-dlp download failed!")

        with os.scandir(tmpdir) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                video_id, name = entry.name.split(".", maxsplit=1)
                yield video_id, name, entry.path
