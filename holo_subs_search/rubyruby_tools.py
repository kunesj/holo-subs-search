from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import pathlib
import shutil
import tempfile
import time
from typing import AsyncIterator, Literal, Self

import aiohttp

from .env_config import RUBYRUBY_ALLOW_UNSUPPORTED_FILES, RUBYRUBY_PARALLEL_COUNT

RubyRubyFileType = Literal[
    "rubyruby", "info", "description", "readme", "chat", "video-only", "audio-only", "video", "thumbnail", "unsupported"
]

_logger = logging.getLogger(__name__)
RUBYRUBY_SEMAPHORE = asyncio.Semaphore(RUBYRUBY_PARALLEL_COUNT)


class RubyRubyError(Exception):
    pass


class RubyRubyNotFound(RubyRubyError):
    pass


@dataclasses.dataclass
class RubyRubyFile:
    file_type: RubyRubyFileType
    file_name: str
    file_size: int | None = None
    url: str | None = None
    path: pathlib.Path | None = None

    @classmethod
    def from_data(cls: type[Self], data: dict) -> Self:
        file_name = data["name"]
        mime_type = data["file"]["mimeType"]

        if mime_type.startswith("audio/"):
            file_type: RubyRubyFileType = "audio-only"

        elif mime_type.startswith("video/") and "+" in file_name.split(".", maxsplit=1)[-1]:
            file_type = "video"

        elif mime_type.startswith("video/"):
            file_type = "video-only"

        elif mime_type.startswith("image/") or any(file_name.endswith(x) for x in (".webp", ".jpg", ".png")):
            file_type = "thumbnail"

        # *.live_chat.json.7z
        elif ".live_chat.json" in file_name:
            file_type = "chat"

        elif file_name.endswith(".info"):
            file_type = "info"

        elif file_name.endswith(".description"):
            file_type = "description"

        elif file_name == "README.md":
            file_type = "readme"

        elif RUBYRUBY_ALLOW_UNSUPPORTED_FILES:
            _logger.error("Unsupported file: %s", file_name)
            file_type = "unsupported"

        else:
            raise ValueError("Unsupported rubyruby file", file_name)

        return cls(
            file_type=file_type,
            file_name=file_name,
            file_size=data["size"],
            url=data["@microsoft.graph.downloadUrl"],
        )


async def download_video(
    *,
    video_id: str,
    members: bool = False,
    download_audio: bool = False,
    download_chat: bool = False,
    timeout: aiohttp.ClientTimeout | None = None,
) -> AsyncIterator[RubyRubyFile]:
    async with RUBYRUBY_SEMAPHORE, aiohttp.ClientSession() as session:
        response = await session.get(
            url="https://streams.rubyruby.net/api/watch",
            params={"videoId": video_id, "members": "true" if members else "false"},
            timeout=timeout,
        )

        if response.status == 404:
            raise RubyRubyNotFound("Video not found", video_id, members)
        elif response.status >= 400:
            raise RubyRubyError(response.content, response.status)

        response.raise_for_status()
        rubyruby_info = await response.json()

        # get list of files to download

        all_rubyruby_files = [RubyRubyFile.from_data(file_data) for file_data in rubyruby_info["files"]]
        _logger.debug(all_rubyruby_files)

        rubyruby_files = [x for x in all_rubyruby_files if x.file_type in ("rubyruby", "info")]

        if download_audio:
            rubyruby_files += [x for x in all_rubyruby_files if x.file_type == "audio-only"]

        if download_audio and not any(x.file_type == "audio-only" for x in rubyruby_files):
            rubyruby_files += [x for x in all_rubyruby_files if x.file_type == "video"]

        if download_chat:
            rubyruby_files += [x for x in all_rubyruby_files if x.file_type == "chat"]

        # download files

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)

            # write rubyruby metadata

            rubyruby_name = f"{video_id}.rubyruby.json"
            rubyruby_path = tmpdir_path / rubyruby_name
            rubyruby_path.write_text(json.dumps(rubyruby_info))
            rubyruby_files.append(RubyRubyFile(file_type="rubyruby", file_name=rubyruby_name, path=rubyruby_path))

            # download
            # - request sometimes returns an error. rerun it if you get one

            for rubyruby_file in rubyruby_files:
                if rubyruby_file.path:
                    continue

                _logger.info("Downloading: %r", rubyruby_file)
                response = await session.get(url=rubyruby_file.url, timeout=timeout)
                response.raise_for_status()

                file_path = tmpdir_path / rubyruby_file.file_name
                downloaded_size = 0
                last_log = 0.0

                with file_path.open("wb") as f:
                    async for data in response.content.iter_chunked(2**25):  # 32Mb
                        downloaded_size += len(data)

                        if (time.time() - last_log) > 1.0 or downloaded_size == rubyruby_file.file_size:
                            _logger.info(
                                "Downloaded %s%%, %s/%s",
                                round((downloaded_size / rubyruby_file.file_size) * 100, 2),
                                downloaded_size,
                                rubyruby_file.file_size,
                            )
                            last_log = time.time()

                        f.write(data)

                rubyruby_file.path = file_path

            # yield results

            for rubyruby_file in rubyruby_files:
                yield rubyruby_file


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--video-id", required=True, help="`-v jXLHo3kC7r4` ID od youtube video to download")
    parser.add_argument("--save", help="Path where should the files be saved")
    parser.add_argument("--members", action="store_true")
    parser.add_argument(
        "-d",
        "--debug",
        type=int,
        choices=[50, 40, 30, 20, 10, 1],
        default=20,
        help="Set global debug level [CRITICAL=50, ERROR=40, WARNING=30, INFO=20, DEBUG=10, SPAM=1]",
    )
    args = parser.parse_args()

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(args.debug)

    if args.save:
        save_path = pathlib.Path(args.save)
        if not save_path.is_dir() or not save_path.exists():
            raise ValueError("Save path must be existing directory")
    else:
        save_path = None

    async for item in download_video(video_id=args.video_id, members=args.members):
        _logger.info("Downloaded: %r", item)
        if save_path:
            shutil.copy(item.path, save_path / os.path.basename(item.path))


if __name__ == "__main__":
    asyncio.run(main())
