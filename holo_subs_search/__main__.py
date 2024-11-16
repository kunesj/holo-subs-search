#!/usr/bin/env python3.11

import argparse
import logging
import os
import pathlib

from . import holodex_downloader
from .storage import ChannelRecord, Storage, VideoRecord

_logger = logging.getLogger(__name__)

if __name__ == "__main__":
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
        "--fetch-subtitles",
        action="store_true",
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
            if channel.holodex_id and channel.refresh_holodex_info:
                fetch_holodex_ids.add(channel.holodex_id)

    if args.fetch_org_channels:
        _logger.info("Fetching %r channels...", args.fetch_org_channels)
        for value in holodex_downloader.download_org_channels(org=args.fetch_org_channels):
            ChannelRecord.from_holodex(storage=storage, value=value)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.info("Refreshing stored channels...")
        for value in holodex_downloader.download_channels(channel_ids=set(fetch_holodex_ids)):
            ChannelRecord.from_holodex(storage=storage, value=value)
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
            VideoRecord.from_holodex(storage=storage, value=value)
