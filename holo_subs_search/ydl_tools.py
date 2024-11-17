#!/usr/bin/env python3.11

import logging
import os
import tempfile
import time
from typing import Any, Iterator, Sequence

import yt_dlp

_logger = logging.getLogger(__name__)


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

    # Anonymous requests don't get HTTP 429 errors as easily, so we don't have to wait with them by default
    if cookies_from_browser or rate_limit_count > 0:
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
    video_ids: Sequence[str], langs: list[str], cookies_from_browser: str | None = None
) -> Iterator[tuple[str, str, str]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        # download all new files

        rate_limit_count = 0
        max_rate_limit_count = 5
        while True:
            try:
                with yt_dlp.YoutubeDL(
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

            except yt_dlp.utils.DownloadError as e:
                if "HTTP Error 429" in e.msg and rate_limit_count < max_rate_limit_count:
                    rate_limit_count += 1
                    sleep_time = 2**rate_limit_count
                    _logger.error("Rate limited. Will retry after %s seconds: %s", sleep_time, e)
                    time.sleep(sleep_time)
                    continue
                raise

            break

        # iterate over downloaded files

        with os.scandir(tmpdir) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                video_id, name = entry.name.split(".", maxsplit=1)
                yield video_id, name, entry.path
