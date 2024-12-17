from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import pathlib
import tempfile
from typing import AsyncIterator, Literal, Self

import aiofiles
import aiohttp

RagtagFileType = Literal["ragtag", "info", "chat", "video-only", "audio-only", "video", "thumbnail", "unsupported"]

_logger = logging.getLogger(__name__)

REGTAG_SEMAPHORE = asyncio.Semaphore(1)
RAGTAG_ALLOW_UNSUPPORTED_FILES = bool(os.getenv("RAGTAG_ALLOW_UNSUPPORTED_FILES", ""))


class RagtagError(Exception):
    pass


class RagtagNotFound(RagtagError):
    pass


@dataclasses.dataclass
class RagtagFile:
    file_type: RagtagFileType
    file_name: str
    file_size: int | None = None
    url: str | None = None
    path: pathlib.Path | None = None

    @classmethod
    def from_hit(cls: type[Self], hit: dict) -> list[Self]:
        video_id = hit["_id"]
        source = hit["_source"]
        drive_base = source["drive_base"]

        # https://gist.github.com/AgentOak/34d47c65b1d28829bb17c24c04a0096f
        format_id = source["format_id"]  # 303+251
        video_format_id, audio_format_id = format_id.split("+")

        file_list = []
        for file_info in source["files"]:
            file_name = file_info["name"]

            if file_name.endswith(".info.json"):
                file_type: RagtagFileType = "info"
            elif file_name.endswith(".chat.json") or file_name.endswith(".live_chat.json"):
                file_type = "chat"
            elif file_name.startswith(f"{video_id}.f{video_format_id}."):  # usually .webm
                file_type = "video-only"
            elif file_name.startswith(f"{video_id}.f{audio_format_id}."):  # usually .webm
                file_type = "audio-only"
            elif file_name in (f"{video_id}.webm", f"{video_id}.mp4", f"{video_id}.mkv"):
                file_type = "video"
            elif any(file_name.endswith(x) for x in (".webp", ".jpg", ".png")):
                file_type = "thumbnail"
            elif RAGTAG_ALLOW_UNSUPPORTED_FILES:
                _logger.error("Unsupported file: %s: %s", video_id, file_name)
                file_type = "unsupported"
            else:
                raise ValueError("Unsupported ragtag file", video_id, file_name)

            file_list.append(
                cls(
                    file_type=file_type,
                    file_name=file_name,
                    file_size=file_info.get("size"),
                    url=f"https://content.archive.ragtag.moe/{drive_base}/{video_id}/{file_name}",
                )
            )

        return file_list


# FIXME: use this if youtube video is unavailable or privated
async def download_video(
    *,
    video_id: str,
    download_audio: bool = False,
    download_chat: bool = False,
    timeout: aiohttp.ClientTimeout | None = None,
) -> AsyncIterator[RagtagFile]:
    """
    Examples of returned filenames:
        info.json
        proper.en.srt
        transcription.en.srt
        translation.en.srt
        f123.m4a
    """
    # download_subtitles = download_subtitles or []
    # done_subtitles: dict[str, tuple[str, pathlib.Path]] = {}

    async with aiohttp.ClientSession() as session:
        # get ragtag info.json

        response = await session.get(
            url="https://archive.ragtag.moe/api/v1/search",
            params={"v": video_id},
            timeout=timeout,
        )
        response.raise_for_status()
        search_result = await response.json()

        # get hit

        hits = search_result["hits"]["hits"]
        if not hits:
            raise RagtagNotFound("Video not found", video_id)

        if len(hits) > 1:
            _logger.warning("Unexpectedly got multiple hits, will use the first one")
        hit = hits[0]

        if hit.get("_index") != "youtube-archive":
            raise ValueError("Unsupported hit _index", hit)
        if hit.get("_id") != video_id:
            raise ValueError("Unexpected video ID!", video_id, hit)

        # get list of files to download

        all_ragtag_files: list[RagtagFile] = RagtagFile.from_hit(hit)
        _logger.debug(all_ragtag_files)

        ragtag_files = [x for x in all_ragtag_files if x.file_type in ("ragtag", "info")]

        if download_audio:
            ragtag_files += [x for x in all_ragtag_files if x.file_type == "audio-only"]

        if download_audio and not any(x.file_type == "audio-only" for x in ragtag_files):
            ragtag_files += [x for x in all_ragtag_files if x.file_type == "video"]

        if download_chat:
            ragtag_files += [x for x in all_ragtag_files if x.file_type == "chat"]

        # download files

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)

            # write ragtag metadata

            hit_name = f"{video_id}.ragtag.json"
            hit_path = tmpdir_path / hit_name
            hit_path.write_text(json.dumps(hit))
            ragtag_files.append(RagtagFile(file_type="ragtag", file_name=hit_name, path=hit_path))

            # download

            for ragtag_file in ragtag_files:
                if ragtag_file.path:
                    continue

                _logger.info("Downloading: %r", ragtag_file)
                response = await session.get(url=ragtag_file.url, timeout=timeout)
                response.raise_for_status()

                file_path = tmpdir_path / ragtag_file.file_name
                async for data in response.content.iter_chunked(2 * 25):  # 32Mb
                    async with aiofiles.open(file_path, "ba") as f:
                        await f.write(data)
                ragtag_file.path = file_path

            # yield results

            for ragtag_file in ragtag_files:
                yield ragtag_file


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--video-id", required=True, help="`-v wQxKp6trj5g` ID od youtube video to download")
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

    async for ragtag_file in download_video(video_id=args.video_id):
        _logger.info("Downloaded: %r", ragtag_file)


if __name__ == "__main__":
    asyncio.run(main())
