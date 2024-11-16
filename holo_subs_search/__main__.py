#!/usr/bin/env python3.11

import argparse
import datetime
import logging
import os
import pathlib

import yt_dlp

from . import holodex_downloader, ydl_downloader
from .storage import ChannelRecord, Storage, VideoRecord

_logger = logging.getLogger(__name__)


def _fetch_video_subtitles(video: VideoRecord, langs: list[str], cookies_from_browser: str | None = None) -> None:
    _logger.info("Fetching Youtube subtitles for video %s", video.id)

    # fetch info.json and subtitles

    try:
        for yt_id, name, file_path in ydl_downloader.download_video_info_and_subtitles(
            video_ids=[video.youtube_id], langs=langs, cookies_from_browser=cookies_from_browser
        ):
            if name == "info.json":
                pass  # not needed with holodex.json
            elif name.endswith(".srt"):
                with open(file_path, "r") as f:
                    video.save_subtitles(f"youtube.{name}", f.read())  # youtube.en.srt
            else:
                _logger.warning("Fetched unexpected file: %s", name)

    except yt_dlp.utils.DownloadError as e:
        if "members-only" in e.msg and not video.members_only:
            _logger.error("Unexpected members-only download error, marking video as members-only: %s", e)
            video.members_only = True
        elif "Private video" in e.msg or "This video is private" in e.msg:
            _logger.error("Private video, subtitle fetch will be disabled: %s", e)
            video.fetch_subtitles = True
        elif "Video unavailable" in e.msg:
            _logger.error("Unavailable video, subtitle fetch will be disabled: %s", e)
            video.fetch_subtitles = True
        else:
            raise

    else:
        # disable subtitle fetch for videos without any that were published 1+week ago

        week_ago = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=7)
        has_subtitles = bool(list(video.list_subtitles()))
        is_old = video.published_at is None or video.published_at <= week_ago

        if not has_subtitles and is_old:
            _logger.info("No subtitles fetched for older video %s, will be skipped next time", video.id)
            video.fetch_subtitles = False


# flake8: noqa: C801
def main() -> None:
    # parse arguments

    parser = argparse.ArgumentParser()
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
        default="en,jp,id",
    )
    parser.add_argument(
        "--youtube-members",
        default="",
        help="`ID,ID,ID` Youtube IDs of channels that should also fetch membership videos",
    )
    parser.add_argument(
        "--youtube-cookies-from-browser", default=None, help="Eg. `chrome`, see yt-dlp docs for more options"
    )
    parser.add_argument(
        "--process-subtitles",
        action="store_true",
    )
    parser.add_argument(
        "--search-subtitles",
        default=None,
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

    data_path = (pathlib.Path(os.path.dirname(__file__)) / "../data/").absolute()
    storage = Storage(path=data_path)

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
            VideoRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)

    # fetching subtitles

    if args.fetch_subtitles:
        _logger.info("Fetching subtitles...")
        langs = [x_s for x in args.fetch_subtitles_langs.split(",") if (x_s := x.strip())]
        youtube_members = [x_s for x in args.youtube_members.split(",") if (x_s := x.strip())]

        fetch_videos = []

        for video in storage.list_videos():
            if video.youtube_id and video.fetch_subtitles and not list(video.list_subtitles()):
                if video.members_only:
                    channel = storage.get_channel(video.channel_id)
                    if not channel.exists() or channel.youtube_id not in youtube_members:
                        continue
                _fetch_video_subtitles(video, langs, cookies_from_browser=args.youtube_cookies_from_browser)


if __name__ == "__main__":
    main()
