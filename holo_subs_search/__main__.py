#!/usr/bin/env python3.11

import argparse
import datetime
import logging
import os
import pathlib
import time

import termcolor

from . import holodex_tools, sub_parser, sub_search
from .storage import ChannelRecord, Flags, Storage, VideoRecord
from .storage.content_item import ContentItemType

_logger = logging.getLogger(__name__)
DIR_PATH = pathlib.Path(os.path.dirname(__file__))
DEFAULT_STORAGE_PATH = (DIR_PATH / "../data/").absolute()


def _search_video_subtitles(
    storage: Storage,
    value: str,
    *,
    regex: bool = False,
    video_filter: Callable[[VideoRecord], bool] | None = None,
    filter_source: list[str] | None = None,
    filter_lang: list[str] | None = None,
    time_before: int = 15,
    time_after: int = 15,
) -> None:
    def _item_filter(x: ContentItemType) -> bool:
        return (
            x.item_type == "subtitle"
            and (filter_source is None or x.source in filter_source)
            and (filter_lang is None or x.lang in filter_lang)
            and x.subtitle_file.endswith(".srt")
        )

    for video in storage.list_videos(video_filter):
        for item in video.list_content(_item_filter):
            content = item.subtitle_path.read_text()
            parsed = sub_parser.SubFile(
                timestamp=time.time(),
                source=item.source,
                lang=item.lang,
                lines=[x for x in sub_parser.parse_srt_file(content)],
            )
            searchable = sub_search.SearchableSubFile.from_sub_file(parsed)

            header_printed = False
            for match_idx, indexes in enumerate(searchable.search(value=value, regex=regex)):
                # print header with general info about the video

                if not header_printed:
                    parts = [
                        video.published_at.strftime("%Y-%m-%d") if video.published_at else None,
                        video.id,
                        parsed.lang,
                    ]

                    if Flags.YOUTUBE_MEMBERSHIP in video.flags:
                        parts.append("members-only")

                    parts.append(video.title)
                    termcolor.cprint(f">>>>>>>>>> {' | '.join(parts)}", color="green", attrs=["bold"])
                    header_printed = True

                # print timestamp of the match and url to open it

                ts_line = searchable.lines[indexes[0]]
                ts_seconds = int(ts_line.start.total_seconds())
                ts_url = f"{video.youtube_url}&t={ts_seconds}"
                termcolor.cprint(f">>>>> {datetime.timedelta(seconds=ts_seconds)} | {ts_url}", attrs=["bold"])

                # expand range of printed lines to add context

                left_edge_index = searchable.index_to_past_index(
                    indexes[0], delta=datetime.timedelta(seconds=time_before)
                )
                right_edge_index = searchable.index_to_future_index(
                    indexes[-1], delta=datetime.timedelta(seconds=time_after)
                )

                # print match lines

                for line_idx in range(left_edge_index, right_edge_index + 1):
                    ts_line = searchable.lines[line_idx]
                    ts_seconds = int(ts_line.start.total_seconds())

                    if line_idx in indexes:
                        ts_content = termcolor.colored(ts_line.content, "magenta")
                    else:
                        ts_content = ts_line.content

                    print(f"{datetime.timedelta(seconds=ts_seconds)} | {ts_content}")


# flake8: noqa: C801
def main() -> None:
    # parse arguments

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--storage",
        default=DEFAULT_STORAGE_PATH,
    )
    parser.add_argument(
        "-d",
        "--debug",
        type=int,
        choices=[50, 40, 30, 20, 10, 1],
        default=20,
        help="Set global debug level [CRITICAL=50, ERROR=40, WARNING=30, INFO=20, DEBUG=10, SPAM=1]",
    )
    # ---- fetching metadata ----
    parser.add_argument(
        "--fetch-org-channels",
        default=None,  # "All Vtubers", "Hololive", "Nijisanji", "Independents"
    )
    parser.add_argument(
        "--refresh-channels",
        action="store_true",
    )
    parser.add_argument(
        "--refresh-videos",
        action="store_true",
    )
    parser.add_argument(
        "--update-stored",
        action="store_true",
        help="If already stored Holodex/Youtube/... info should be updated",
    )
    # ---- filters ----
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
    # ---- YouTube ----
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
    # ---- Whisper ----
    parser.add_argument(
        "--whisper-transcribe-audio",
        action="store_true",
    )
    parser.add_argument(
        "--whisper-api-key",
        default="placeholder",  # can be empty/placeholder for local api
    )
    parser.add_argument(
        "--whisper-api-base-url",
        default="http://localhost:8000/v1/",
        help="Url of OpenAI-compatible API with whisper support.",
    )
    parser.add_argument(
        "--whisper-model-size",
        default=None,
        choices=["tiny", "base", "small", "medium", "large"],
        help="Size of Whisper model to load. See https://pypi.org/project/openai-whisper/ for more info.",
    )
    parser.add_argument(
        "--whisper-model-name",
        default=None,
        help=(
            "Name of specific Whisper model to load. "
            "Use HuggingFace model names with OpenAI-compatible API, or `whisper-1` with official OpenAI API. "
            "Can't be combined together with --whisper-model-size."
        ),
    )
    # ---- search subtitles ----
    parser.add_argument(
        "--search",
        default=None,
    )
    parser.add_argument(
        "--search-regex",
        action="store_true",
    )
    parser.add_argument(
        "--search-sources",
        nargs="+",
        type=str,
        default=[],
        help="`--search-sources youtube foo bar`",
    )
    parser.add_argument(
        "--search-langs",
        nargs="+",
        type=str,
        default=["en"],
        help="`--search-langs en ja jp id`",
    )
    args = parser.parse_args()

    # logger configuration

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(args.debug)

    # storage

    storage_path = pathlib.Path(args.storage)
    _logger.info("Storage: %s", storage_path)
    storage = Storage(path=storage_path)

    # build filters

    channel_filter = ChannelRecord.build_str_filter(*args.channel_filter)
    video_filter = VideoRecord.build_str_filter(*args.video_filter)

    # fetch/refresh channels

    fetch_holodex_ids = set()

    if args.refresh_channels:
        for channel in storage.list_channels(channel_filter):
            if channel.holodex_id and Flags.HOLODEX_PRESERVE not in channel.flags and args.update_stored:
                fetch_holodex_ids.add(channel.holodex_id)

    if args.fetch_org_channels:
        _logger.info("Fetching %r channels...", args.fetch_org_channels)
        for value in holodex_tools.download_org_channels(org=args.fetch_org_channels):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.info("Refreshing stored channels...")
        for value in holodex_tools.download_channels(channel_ids=set(fetch_holodex_ids)):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.error("Some Holodex channels are indexed, but could not be fetched: %s", fetch_holodex_ids)

    # refreshing/fetching video info

    if args.refresh_videos:
        _logger.info("Refreshing videos...")

        holodex_channel_ids = {
            channel.holodex_id
            for channel in storage.list_channels(channel_filter)
            if channel.holodex_id and Flags.MENTIONS_ONLY not in channel.flags
        }
        for value in holodex_tools.download_channel_video_info(holodex_channel_ids):
            if value.status in ("new", "upcoming", "live"):
                continue
            video = VideoRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            video.update_gitignore()

    # fetching content

    if args.youtube_fetch_subtitles or args.youtube_fetch_audio:
        _logger.info("Fetching YouTube content...")
        yt_video_filter = lambda x: video_filter(x) and x.youtube_id

        for video in storage.list_videos(yt_video_filter):
            # check if video can be accessed

            # FIXME: a way to refetch private/unavailable/memberships
            if Flags.YOUTUBE_PRIVATE in video.flags:
                continue
            elif Flags.YOUTUBE_UNAVAILABLE in video.flags:
                continue
            elif Flags.YOUTUBE_AGE_RESTRICTED in video.flags and not args.youtube_cookies_from_browser:
                continue

            if Flags.YOUTUBE_MEMBERSHIP in video.flags:
                channel = storage.get_channel(video.channel_id)
                if not channel.exists() or channel.youtube_id not in args.youtube_memberships:
                    continue  # not accessible membership video

            # calculate what subtitles to download

            download_subtitles = None
            if args.youtube_fetch_subtitles:
                fetch_langs = set(args.youtube_fetch_subtitles_langs) - set(video.youtube_subtitles.keys())
                for item in video.list_content(
                    lambda x: x.item_type == "subtitle" and x.source == "youtube" and x.lang in fetch_langs
                ):
                    fetch_langs -= {item.lang}

                if fetch_langs:
                    download_subtitles = list(fetch_langs)

            # calculate if audio should be downloaded

            download_audio = False
            if args.youtube_fetch_audio:
                download_audio = (
                    len([*video.list_content(lambda x: x.item_type == "audio" and x.source == "youtube")]) == 0
                )

            # download data

            if download_subtitles or download_audio:
                video.fetch_youtube(
                    download_subtitles=download_subtitles,
                    download_audio=download_audio,
                    cookies_from_browser=args.youtube_cookies_from_browser,
                )

        for video in storage.list_videos(yt_video_filter):
            video.update_gitignore()

    # transcribe audio with whisper

    if args.whisper_transcribe_audio:
        _logger.info("Fetching and transcribing audio into subtitles with Whisper...")

        for video in storage.list_videos(video_filter):
            whisper_subtitles = list(video.list_content(lambda x: x.item_type == "subtitle" and x.source == "whisper"))
            if whisper_subtitles:
                continue

            video.whisper_transcribe_audio(
                api_base_url=args.whisper_api_base_url,
                api_key=args.whisper_api_key,
                model_size=args.whisper_model_size,
                model_name=args.whisper_model_name,
            )

    # searching parsed subtitles

    if args.search is not None:
        _logger.info("Searching subtitles...")
        _search_video_subtitles(
            storage,
            value=args.search,
            regex=args.search_regex,
            video_filter=video_filter,
            filter_source=args.search_sources or None,
            filter_lang=args.search_langs or None,
        )


if __name__ == "__main__":
    main()
