#!/usr/bin/env python3.11

import os
import tempfile
from typing import Any, Iterator, Sequence

from yt_dlp import YoutubeDL


def get_video_params(
    download_path: str, langs: list[str], cookies_from_browser: str | None = None, rate_limit_count: int = 0
) -> dict[str, Any]:
    params = {
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
            # Used by temp files, I have stripped it to just ID to fix the "File name too long" error
            "default": "%(id)s.%(ext)s",
            # ID.en.srt
            "subtitle": "%(id)s.%(ext)s",
            # ID.info.json
            "infojson": "%(id)s",
        },
    }

    if cookies_from_browser:
        params |= {
            # try to prevent HTTP 429
            # "sleep_interval_requests": None,
            # "sleep_interval": None,
            # "max_sleep_interval": None,
            "sleep_interval_subtitles": 2
            ** rate_limit_count,
        }

    return params


def download_video_info_and_subtitles(
    video_ids: Sequence[str], langs: list[str], cookies_from_browser: str | None = None, rate_limit_count: int = 0
) -> Iterator[tuple[str, str, str]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        # download all new files

        with YoutubeDL(
            params=get_video_params(
                download_path=tmpdir,
                langs=langs,
                cookies_from_browser=cookies_from_browser,
                rate_limit_count=rate_limit_count,
            )
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
