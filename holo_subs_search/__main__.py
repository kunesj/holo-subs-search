#!/usr/bin/env python3.11

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import os
import pathlib
import shutil
import sys
from typing import Callable

import termcolor

from . import diarization, holodex_tools, transcription
from .env_config import (
    HOLODEX_PARALLEL_COUNT,
    PYANNOTE_BASE_URLS,
    PYANNOTE_PARALLEL_COUNTS,
    VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT,
    VIDEO_PROCESS_PARALLEL_COUNT,
    VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT,
    VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT,
    WHISPER_BASE_URLS,
    WHISPER_PARALLEL_COUNTS,
    YTDL_PARALLEL_COUNT,
)
from .logging_config import logging_with_values, setup_logging
from .storage import ChannelRecord, FilterPart, Flags, Storage, VideoRecord
from .storage.content_item import MULTI_LANG, AudioItem, SubtitleItem
from .utils import with_semaphore

_logger = logging.getLogger(__name__)
DIR_PATH = pathlib.Path(os.path.dirname(__file__))
DEFAULT_STORAGE_PATH = (DIR_PATH / "../data/").absolute()


def _search_video_subtitles(
    storage: Storage,
    value: str,
    *,
    regex: bool = False,
    video_filter: Callable[[VideoRecord], bool] | None = None,
    subtitle_filter: Callable[[SubtitleItem], bool] | None = None,
    time_before: int = 15,
    time_after: int = 15,
) -> None:
    if not subtitle_filter:
        subtitle_filter = SubtitleItem.build_filter()

    for video in storage.list_videos(video_filter):
        for item in video.list_content(subtitle_filter):
            tx = item.load_transcription()
            searchable = transcription.SearchableTranscription.from_transcription(tx)

            header_printed = False
            for match_idx, indexes in enumerate(searchable.search(value=value, regex=regex)):
                # print header with general info about the video

                if not header_printed:
                    parts = [
                        video.published_at.strftime("%Y-%m-%d") if video.published_at else None,
                        video.id,
                        item.content_id,
                        ",".join(tx.get_main_langs()),
                    ]

                    if Flags.YOUTUBE_MEMBERSHIP in video.flags:
                        parts.append("members-only")

                    parts.append(video.title)
                    termcolor.cprint(f">>>>>>>>>> {' | '.join(parts)}", color="green", attrs=["bold"])
                    header_printed = True

                # print timestamp of the match and url to open it

                ts_segment = searchable.segments[indexes[0]]
                ts_seconds = int(ts_segment.start)
                ts_url = f"{video.youtube_url}&t={ts_seconds}"
                termcolor.cprint(f">>>>> {datetime.timedelta(seconds=ts_seconds)} | {ts_url}", attrs=["bold"])

                # expand range of printed lines to add context

                left_edge_index = searchable.index_to_past_index(indexes[0], delta_t=time_before)
                right_edge_index = searchable.index_to_future_index(indexes[-1], delta_t=time_after)

                # print match lines

                for line_idx in range(left_edge_index, right_edge_index + 1):
                    ts_segment = searchable.segments[line_idx]
                    ts_seconds = int(ts_segment.start)

                    if line_idx in indexes:
                        ts_content = termcolor.colored(ts_segment.text, "magenta")
                    else:
                        ts_content = ts_segment.text

                    print(f"{datetime.timedelta(seconds=ts_seconds)} | {ts_content}")


@with_semaphore(VIDEO_PROCESS_PARALLEL_COUNT)
@logging_with_values(get_context=lambda args, video, *_, **__: [f"video={video.id}"])
async def _process_video(args: argparse.Namespace, video: VideoRecord) -> None:
    # fetching YouTube content
    # - fallback to archives if YT is unavailable or privated

    if args.youtube_fetch_subtitles or args.youtube_fetch_audio and video.youtube_id:
        await video.fetch_youtube(
            download_subtitles=args.youtube_fetch_subtitles_langs if args.youtube_fetch_subtitles else None,
            download_audio=args.youtube_fetch_audio,
            cookies_from_browser=args.youtube_cookies_from_browser,
            memberships=args.youtube_memberships,
            force=args.youtube_force,
        )
        video.update_gitignore()

    if args.ragtag_fetch_audio and video.youtube_id:
        await video.fetch_ragtag(
            download_audio=args.ragtag_fetch_audio,
            force=args.ragtag_force,
        )
        video.update_gitignore()

    if args.rubyruby_fetch_audio and video.youtube_id:
        await video.fetch_rubyruby(
            download_audio=args.rubyruby_fetch_audio,
            force=args.rubyruby_force,
        )
        video.update_gitignore()

    # diarize audio with pyannote

    if args.pyannote_diarize_audio:
        await video.pyannote_diarize_audio(
            checkpoint=args.pyannote_checkpoint,
            force=args.pyannote_force,
        )

    # transcribe audio with whisper

    if args.whisper_transcribe_audio:
        await video.whisper_transcribe_audio(
            model=args.whisper_model,
            langs=args.whisper_langs,
            force=args.whisper_force,
        )

    # clear audio

    if args.youtube_clear_audio:
        for audio_item in video.list_content(
            AudioItem.build_filter(FilterPart(name="source", operator="eq", value="youtube"))
        ):
            _logger.info("Clearing audio item %r of video %r", audio_item.content_id, video.id)
            shutil.rmtree(audio_item.path)

    if args.ragtag_clear_audio:
        for audio_item in video.list_content(
            AudioItem.build_filter(FilterPart(name="source", operator="eq", value="ragtag"))
        ):
            _logger.info("Clearing audio item %r of video %r", audio_item.content_id, video.id)
            shutil.rmtree(audio_item.path)


# flake8: noqa: C801
async def main() -> None:
    # parse arguments

    parser = argparse.ArgumentParser()
    # region
    parser.add_argument(
        "--storage",
        default=DEFAULT_STORAGE_PATH,
    )
    parser.add_argument(
        "--storage-git-privacy",
        choices=["private", "public"],
        default=None,
        help="Sets storage to specified privacy level. "
        "Storage with 'public' privacy level will automatically create `.gitignore` "
        "files that will exclude membership content from git.",
    )
    parser.add_argument(
        "-d",
        "--debug",
        type=int,
        choices=[50, 40, 30, 20, 10, 1],
        default=20,
        help="Set global debug level [CRITICAL=50, ERROR=40, WARNING=30, INFO=20, DEBUG=10, SPAM=1]",
    )
    parser.add_argument(
        "--channel-filter",
        nargs="+",
        type=str,
        default=[],
        help="`--channel-filter id:eq:***** flags:excludes:****` Can be used to limit what channels are processed. "
        "Used only when refreshing channels or video lists.",
    )
    parser.add_argument(
        "--video-filter",
        nargs="+",
        type=str,
        default=[],
        help="`--video-filter id:eq:***** flags:excludes:****` Can be used to limit what videos are processed",
    )
    # endregion
    # ---- Holodex ----
    # region
    parser.add_argument(
        "--holodex-fetch-org-channels",
        default=None,  # "All Vtubers", "Hololive", "Nijisanji", "Independents"
    )
    parser.add_argument(
        "--holodex-refresh-channels",
        action="store_true",
    )
    parser.add_argument(
        "--holodex-refresh-videos",
        action="store_true",
    )
    parser.add_argument(
        "--holodex-update-info",
        action="store_true",
        help="If already stored Holodex info should be updated",
    )
    # endregion
    # ---- YouTube ----
    # region
    parser.add_argument(
        "--youtube-memberships",
        nargs="+",
        type=str,
        default=[],
        help="`--youtube-memberships ID ID ID` Youtube IDs of channels that should also fetch membership videos",
    )
    parser.add_argument(
        "--youtube-cookies-from-browser",
        default=None,
        help="Eg. `chrome`, see yt-dlp docs for more options",
    )
    parser.add_argument(
        "--youtube-fetch-subtitles",
        action="store_true",
    )
    parser.add_argument(
        "--youtube-fetch-subtitles-langs",
        nargs="+",
        type=str,
        default=["en"],
        help="`--youtube-fetch-subtitles-langs en jp id`",
    )
    parser.add_argument(
        "--youtube-fetch-audio",
        action="store_true",
    )
    parser.add_argument(
        "--youtube-clear-audio",
        action="store_true",
        help="Delete downloaded youtube audio",
    )
    parser.add_argument(
        "--youtube-force",
        action="store_true",
        help="Don't skip already processed or unavailable items",
    )
    # endregion
    # ---- Ragtag Archive (ragtag.moe) ----
    # region
    parser.add_argument(
        "--ragtag-fetch-audio",
        action="store_true",
        help="Will try to fetch unavailable videos from Ragtag Archive. "
        "Videos without `youtube-unavailable` or `youtube-private` flags are automatically skipped.",
    )
    parser.add_argument(
        "--ragtag-clear-audio",
        action="store_true",
        help="Delete downloaded ragtag audio",
    )
    parser.add_argument(
        "--ragtag-force",
        action="store_true",
        help="Don't skip already processed or unavailable items",
    )
    # endregion
    # ---- RubyRuby Archive (streams.rubyruby.net) ----
    # region
    parser.add_argument(
        "--rubyruby-fetch-audio",
        action="store_true",
        help="Will try to fetch unavailable videos from RubyRuby Archive. "
        "Videos without `youtube-unavailable` or `youtube-private` flags are automatically skipped.",
    )
    parser.add_argument(
        "--rubyruby-clear-audio",
        action="store_true",
        help="Delete downloaded rubyruby audio",
    )
    parser.add_argument(
        "--rubyruby-force",
        action="store_true",
        help="Don't skip already processed or unavailable items",
    )
    # endregion
    # ---- Pyannote ----
    # region
    parser.add_argument(
        "--pyannote-diarize-audio",
        action="store_true",
    )
    parser.add_argument(
        "--pyannote-checkpoint",
        default=diarization.DIARIZATION_CHECKPOINT,
    )
    parser.add_argument(
        "--pyannote-force",
        action="store_true",
        help="Don't skip already processed items",
    )
    # endregion
    # ---- Whisper ----
    # region
    parser.add_argument(
        "--whisper-transcribe-audio",
        action="store_true",
    )
    parser.add_argument(
        "--whisper-model",
        default=transcription.model_size_and_audio_lang_to_model(model_size="large", audio_lang=None),
        help=(
            "Name of specific Whisper model to load. "
            "Use HuggingFace model names with OpenAI-compatible API, or `whisper-1` with official OpenAI API."
        ),
    )
    parser.add_argument(
        "--whisper-langs",
        nargs="+",
        type=str,
        default=[MULTI_LANG],
        help=(
            f"`--whisper-langs en ja id {MULTI_LANG}`\n"
            f"- {MULTI_LANG!r} lets whisper automatically detect language of audio chunks, "
            f"the output will contain multiple languages.\n"
            "- Other values will transcribe+translate audio to specified language."
        ),
    )
    parser.add_argument(
        "--whisper-force",
        action="store_true",
        help="Don't skip already processed items",
    )
    # endregion
    # ---- search subtitles ----
    # region
    parser.add_argument(
        "--search",
        default=None,
    )
    parser.add_argument(
        "--search-regex",
        action="store_true",
    )
    parser.add_argument(
        "--search-subtitle-filter",
        nargs="+",
        type=str,
        default=["langs:includes:en"],
        help="`--search-subtitle-filter source:eq:youtube langs:includes:en`",
    )
    # endregion
    args = parser.parse_args()

    # logger configuration

    setup_logging(args.debug)

    _logger.info(
        "Video Parallel: video=%s, ytfetch=%s, pyannote=%s, whisper=%s",
        VIDEO_PROCESS_PARALLEL_COUNT,
        VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT,
        VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT,
        VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT,
    )

    _logger.info("Holodex parallel: %s", HOLODEX_PARALLEL_COUNT)
    _logger.info("ytdl parallel: %s", YTDL_PARALLEL_COUNT)
    _logger.info("Pyannote servers: %s, parallel=%s", PYANNOTE_BASE_URLS, PYANNOTE_PARALLEL_COUNTS)
    _logger.info("Whisper servers: %s, parallel=%s", WHISPER_BASE_URLS, WHISPER_PARALLEL_COUNTS)

    # storage

    storage_path = pathlib.Path(args.storage)
    _logger.info("Storage: %s", storage_path)
    storage = Storage(path=storage_path)

    if git_privacy := args.storage_git_privacy:
        _logger.info("Setting storage git privacy to: %s", git_privacy)
        storage.git_privacy = git_privacy
        for video in storage.list_videos():
            video.update_gitignore()

    # build filters

    channel_filter = ChannelRecord.build_str_filter(*args.channel_filter)
    video_filter = VideoRecord.build_str_filter(*args.video_filter)
    search_subtitle_filter = SubtitleItem.build_str_filter(*args.search_subtitle_filter)

    # fetch/refresh channels

    fetch_holodex_ids = set()

    if args.holodex_refresh_channels:
        for channel in storage.list_channels(channel_filter):
            if channel.holodex_id and Flags.HOLODEX_PRESERVE not in channel.flags and args.holodex_update_info:
                fetch_holodex_ids.add(channel.holodex_id)

    if args.holodex_fetch_org_channels:
        _logger.info("Fetching %r channels...", args.holodex_fetch_org_channels)
        async for value in holodex_tools.download_org_channels(org=args.holodex_fetch_org_channels):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.holodex_update_info)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.info("Refreshing stored channels...")
        async for value in holodex_tools.download_channels(channel_ids=set(fetch_holodex_ids)):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.holodex_update_info)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.error("Some Holodex channels are indexed, but could not be fetched: %s", fetch_holodex_ids)

    # refreshing/fetching video info

    if args.holodex_refresh_videos:
        _logger.info("Refreshing videos...")

        holodex_channel_ids = {
            channel.holodex_id
            for channel in storage.list_channels(channel_filter)
            if channel.holodex_id and Flags.MENTIONS_ONLY not in channel.flags
        }
        async for value in holodex_tools.download_channel_video_info(holodex_channel_ids):
            if value.status in ("new", "upcoming", "live"):
                continue
            video = VideoRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.holodex_update_info)
            video.update_gitignore()

    # process video

    async with asyncio.TaskGroup() as tg:
        for video in storage.list_videos(video_filter):
            coro = _process_video(args, video)
            tg.create_task(coro)

    # searching parsed subtitles

    if args.search is not None:
        _logger.info("Searching subtitles...")
        _search_video_subtitles(
            storage,
            value=args.search,
            regex=args.search_regex,
            video_filter=video_filter,
            subtitle_filter=search_subtitle_filter,
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _logger.info("Stopped by user")
        sys.exit(1)
