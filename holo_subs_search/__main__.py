#!/usr/bin/env python3.11

import argparse
import datetime
import logging
import os
import pathlib
import time

import termcolor
import yt_dlp

from . import holodex_downloader, sub_parser, sub_search, ydl_downloader
from .storage import ChannelRecord, Storage, VideoRecord

_logger = logging.getLogger(__name__)
DEFAULT_STORAGE_PATH = (pathlib.Path(os.path.dirname(__file__)) / "../data/").absolute()


def _fetch_video_subtitles(video: VideoRecord, langs: list[str], cookies_from_browser: str | None = None) -> None:
    _logger.info("Fetching Youtube subtitles for video %s - %s", video.id, video.published_at)

    # fetch info.json and subtitles

    try:
        for yt_id, name, file_path in ydl_downloader.download_video_info_and_subtitles(
            video_ids=[video.youtube_id],
            langs=langs,
            cookies_from_browser=cookies_from_browser,
        ):
            if name == "info.json":
                pass  # not needed with holodex.json
            elif name.endswith(".srt"):
                with open(file_path, "r") as f:
                    video.save_subtitle(f"youtube.{name}", f.read())  # youtube.en.srt
            else:
                _logger.warning("Fetched unexpected file: %s", name)

    except yt_dlp.utils.DownloadError as e:
        if not video.members_only and any(
            x in e.msg for x in ("members-only", "This video is available to this channel's members")
        ):
            _logger.error("Unexpected members-only download error, marking video as members-only: %s", e)
            video.members_only = True
        elif any(x in e.msg for x in ("Private video", "This video is private")):
            _logger.error("Private video, subtitle fetch will be disabled: %s", e)
            video.skip_subtitles += ["all"]
        elif "Video unavailable" in e.msg:
            _logger.error("Unavailable video, subtitle fetch will be disabled: %s", e)
            video.skip_subtitles += ["all"]
        elif "Sign in to confirm your age" in e.msg:
            _logger.error("Age confirmation required. Run again with cookies: %s", e)
        else:
            raise

    else:
        _skip_missing_subtitles(video, langs)


def _skip_missing_subtitles(video: VideoRecord, langs: list[str], days: int = 7) -> None:
    """
    disable subtitle fetch for videos that were published 1+week ago and are missign the subtitles
    """
    week_ago = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=days)
    is_old = video.published_at is None or video.published_at <= week_ago

    if is_old:
        stored_langs = {name.split(".")[1] for name in video.list_subtitles()}
        missing_langs = {lang for lang in langs if lang not in stored_langs}

        if missing_langs:
            _logger.info(
                "No subtitles for %s languages fetched for older video ID=%s, will be skipped next time",
                missing_langs,
                video.id,
            )
            video.skip_subtitles += list(missing_langs)


def _search_video_subtitles(
    storage: Storage,
    value: str,
    *,
    regex: bool = False,
    filter_source: list[str] | None = None,
    filter_lang: list[str] | None = None,
    lines_before: int = 3,  # FIXME: time before/after
    lines_after: int = 3,
) -> None:  # FIXME: unfinished
    for video in storage.list_videos():
        for name in video.list_subtitles(filter_source=filter_source, filter_lang=filter_lang, filter_ext=["srt"]):
            source, lang, ext = name.split(".")

            content = video.load_subtitle(name)
            parsed = sub_parser.SubFile(
                timestamp=time.time(),
                source=source,
                lang=lang,
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

                    if video.members_only:
                        parts.append("members-only")

                    parts.append(video.title)
                    termcolor.cprint(f">>>>>>>>>> {' | '.join(parts)}", color="green", attrs=["bold"])
                    header_printed = True

                # print timestamp of the match and url to open it

                ts_line = searchable.lines[indexes[0]]
                ts_seconds = int(ts_line.start.total_seconds())
                ts_url = f"{video.youtube_url}&t={ts_seconds}"
                termcolor.cprint(f">>>>> {datetime.timedelta(seconds=ts_seconds)} | {ts_url}", attrs=["bold"])

                # print match lines

                left_index = max(indexes[0] - lines_before, 0)
                right_index = min(indexes[-1] + lines_after, len(searchable.lines) - 1)
                for line_idx in range(left_index, right_index + 1):
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
    parser.add_argument(
        "--fetch-subtitles",
        action="store_true",
    )
    parser.add_argument(
        "--fetch-subtitles-langs",
        nargs="+",
        type=str,
        default=["en"],
        help="`--fetch-subtitles-langs en jp id`",
    )
    parser.add_argument(
        "--yt-members",
        nargs="+",
        type=str,
        default=[],
        help="`--yt-members ID ID ID` Youtube IDs of channels that should also fetch membership videos",
    )
    parser.add_argument(
        "--yt-cookies-from-browser", default=None, help="Eg. `chrome`, see yt-dlp docs for more options"
    )
    parser.add_argument(
        "--parse-subtitles",
        action="store_true",
    )
    parser.add_argument(
        "--search",
        default=None,
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
        help="`--search-langs en jp id`",
    )
    parser.add_argument(
        "--search-regex",
        action="store_true",
    )
    parser.add_argument(
        "-d",
        "--debug",
        type=int,
        choices=[50, 40, 30, 20, 10, 1],
        default=20,
        help="Set global debug level [CRITICAL=50, ERROR=40, WARNING=30, INFO=20, DEBUG=10, SPAM=1]",
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

    # fetch/refresh channels

    fetch_holodex_ids = set()

    if args.refresh_channels:
        for channel in storage.list_channels():
            if channel.holodex_id and channel.refresh_holodex_info and args.update_stored:
                fetch_holodex_ids.add(channel.holodex_id)

    if args.fetch_org_channels:
        _logger.info("Fetching %r channels...", args.fetch_org_channels)
        for value in holodex_downloader.download_org_channels(org=args.fetch_org_channels):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.info("Refreshing stored channels...")
        for value in holodex_downloader.download_channels(channel_ids=set(fetch_holodex_ids)):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.error("Some Holodex channels are indexed, but could not be fetched: %s", fetch_holodex_ids)

    # refreshing/fetching video info

    if args.refresh_videos:
        _logger.info("Refreshing videos...")

        holodex_channel_ids = {
            channel.holodex_id for channel in storage.list_channels() if channel.holodex_id and channel.refresh_videos
        }
        for value in holodex_downloader.download_channel_video_info(holodex_channel_ids):
            if value.status in ("new", "upcoming", "live"):
                continue
            VideoRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)

    # fetching subtitles

    if args.fetch_subtitles:
        _logger.info("Fetching subtitles...")

        for video in storage.list_videos():
            if not video.youtube_id:
                continue  # not a youtube video?
            elif "all" in video.skip_subtitles:
                continue  # skip all languages

            fetch_langs = set(args.fetch_subtitles_langs) - set(video.skip_subtitles)
            for name in video.list_subtitles(filter_source=["youtube"], filter_lang=list(fetch_langs)):
                source, lang, ext = name.split(".")
                fetch_langs -= {lang}

            if not fetch_langs:
                continue  # no langs to fetch

            if video.members_only:
                channel = storage.get_channel(video.channel_id)
                if not channel.exists() or channel.youtube_id not in args.yt_members:
                    continue  # not accessible membership video

            _fetch_video_subtitles(video, list(fetch_langs), cookies_from_browser=args.yt_cookies_from_browser)

        for video in storage.list_videos():
            video.update_gitignore()

    # searching parsed subtitles

    if args.search is not None:
        _logger.info("Searching subtitles...")
        _search_video_subtitles(
            storage,
            value=args.search,
            regex=args.search_regex,
            filter_source=args.search_sources or None,
            filter_lang=args.search_langs or None,
        )


if __name__ == "__main__":
    main()
