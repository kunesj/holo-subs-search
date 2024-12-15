from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import tempfile
import time
from types import TracebackType
from typing import Any, AsyncIterator, Self

import yt_dlp

from .env_config import YTDL_PARALLEL_COUNT

_logger = logging.getLogger(__name__)

# */*/*/* - audio formats supported by Whisper; free formats first
# [asr>=16000] - Whisper audio is resampled to 16kHz, so we want files that have higher or equal sampling frequency
# [vcodec=none] - only audio files
# +size - order by size from smallest file first
AUDIO_FORMAT = "(flac/m4a/ogg/wav/webm/mp3/mp4/mpeg/mpga)[asr>=16000][vcodec=none]"
AUDIO_FORMAT_SORT = ["+size"]

# "type" of subtitles - used only to generate filename
PROPER_SUBS = "proper"
TRANSCRIPTION_SUBS = "transcription"
TRANSLATION_SUBS = "translation"


class AsyncYoutubeDL(yt_dlp.YoutubeDL):
    ASYNC_SEMAPHORE = asyncio.Semaphore(YTDL_PARALLEL_COUNT)
    _async_stack = None

    async def __aenter__(self) -> Self:
        """
        Implemented
        """
        if self._async_stack is not None:
            raise ValueError("Already in context")

        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(self.ASYNC_SEMAPHORE)
            stack.enter_context(self)
            self._async_stack = stack.pop_all()

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """
        Implemented
        """
        if self._async_stack is not None:
            result = await self._async_stack.__aexit__(exc_type, exc_val, exc_tb)
            self._async_stack = None
            return result
        return None

    async def async_download(self, url_list: list[str]) -> int:
        return await asyncio.to_thread(self.download, url_list)


def get_video_params(
    *,
    download_path: str,
    download_subtitles: list[str] | None = None,
    download_audio: bool = False,
    automatic_subtitles: bool = False,
    cookies_from_browser: str | None = None,
    rate_limit_count: int = 0,
) -> dict[str, Any]:
    params = {
        "skip_download": True,
        "cookiesfrombrowser": (cookies_from_browser,) if cookies_from_browser else None,
        # download info.json
        "writeinfojson": True,
        "clean_infojson": True,
        # save paths and names
        "paths": {"home": download_path},
        "outtmpl": {
            # Used by temp files, I have stripped it to just ID to fix the "File name too long" error
            # Also used for audio and video files
            "default": "%(id)s.%(format_id)s.%(ext)s",
            # ID.en.srt
            "subtitle": "%(id)s.%(ext)s",
            # ID.info.json
            "infojson": "%(id)s",
        },
    }

    # download automatic subtitles and convert them to SRT format
    if download_subtitles:
        params |= {
            "writeautomaticsub": automatic_subtitles,
            "writesubtitles": True,
            "subtitleslangs": [f"{x}.*" for x in download_subtitles] if automatic_subtitles else download_subtitles,
            "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"}],
            # Skip translated subtitles (e.g. `en-jp`)
            # - The "main" subtitles (e.g. `en`) will still be included even if they are translations
            # - This should result in at most 2 subtitles per language: `en` and `en-orig` for `en.*`
            # - Relevant only if automatic_subtitles=True, otherwise translation should not be downloaded anyway
            # - See https://github.com/yt-dlp/yt-dlp/issues/9371#issuecomment-1978991249 for more info
            "extractor_args": {"youtube": {"skip": ["translated_subs"]}},
        }

    # download smallest usable audio
    if download_audio:
        params |= {
            "skip_download": False,
            "extractaudio": True,
            "format": AUDIO_FORMAT,
            "format_sort": AUDIO_FORMAT_SORT,
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


async def download_video(
    *,
    video_id: str,
    download_subtitles: list[str] | None = None,
    download_audio: bool = False,
    cookies_from_browser: str | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """
    Examples of returned filenames:
        info.json
        proper.en.srt
        transcription.en.srt
        translation.en.srt
        f123.m4a
    """
    download_subtitles = download_subtitles or []
    done_subtitles: dict[str, tuple[str, pathlib.Path]] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        # download everything

        rate_limit_count = 0
        max_rate_limit_count = 5
        while True:
            try:
                # download audio and proper subtitles

                missing_subtitles = set(download_subtitles) - set(done_subtitles.keys())
                async with AsyncYoutubeDL(
                    params=get_video_params(
                        download_path=tmpdir,
                        download_subtitles=[*missing_subtitles],
                        download_audio=download_audio,
                        automatic_subtitles=False,
                        cookies_from_browser=cookies_from_browser,
                        rate_limit_count=rate_limit_count,
                    )
                ) as ydl:
                    # run in separate thread to make download async
                    error_code = await ydl.async_download([f"https://www.youtube.com/watch?v={video_id}"])
                    if error_code != 0:
                        raise Exception("yt-dlp download failed!")

                # rename proper subtitles into "proper.LANG.srt" format and get list of missing subtitles

                with os.scandir(tmpdir) as it:
                    for entry in it:
                        if entry.is_file() and entry.name.endswith(".srt") and entry.name.count(".") == 2:
                            path = pathlib.Path(tmpdir, entry.name)
                            video_id, lang, ext = entry.name.split(".")

                            sub_type = PROPER_SUBS
                            new_path = pathlib.Path(tmpdir, ".".join([video_id, sub_type, lang, ext]))

                            path.rename(new_path)
                            done_subtitles[lang] = (sub_type, new_path)

                # download automatic subtitles

                if missing_subtitles := (set(download_subtitles) - set(done_subtitles.keys())):
                    async with AsyncYoutubeDL(
                        params=get_video_params(
                            download_path=tmpdir,
                            download_subtitles=[*missing_subtitles],
                            download_audio=False,
                            automatic_subtitles=True,
                            cookies_from_browser=cookies_from_browser,
                            rate_limit_count=rate_limit_count,
                        )
                    ) as ydl:
                        error_code = await ydl.async_download([f"https://www.youtube.com/watch?v={video_id}"])
                        if error_code != 0:
                            raise Exception("yt-dlp download failed!")

                # rename automatic subtitles to "transcription.LANG.srt" or "translation.LANG.srt"
                # - keeps only the better one of them

                with os.scandir(tmpdir) as it:
                    for entry in it:
                        if entry.is_file() and entry.name.endswith(".srt") and entry.name.count(".") == 2:
                            path = pathlib.Path(tmpdir, entry.name)
                            video_id, lang, ext = entry.name.split(".")

                            if lang.endswith("-orig"):
                                sub_type = TRANSCRIPTION_SUBS
                                lang = lang[:-5]
                            else:
                                sub_type = TRANSLATION_SUBS
                            new_path = pathlib.Path(tmpdir, ".".join([video_id, sub_type, lang, ext]))

                            if lang in done_subtitles:
                                if done_subtitles[lang][0] in (PROPER_SUBS, TRANSCRIPTION_SUBS):
                                    # better subs are already available
                                    path.unlink()
                                    continue
                                else:
                                    # worse subs are available
                                    done_subtitles[lang][1].unlink()
                                    del done_subtitles[lang]

                            path.rename(new_path)
                            done_subtitles[lang] = (sub_type, new_path)

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
                yield name, entry.path
