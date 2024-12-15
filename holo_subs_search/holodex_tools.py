from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Iterable

from holodex.client import HolodexClient
from holodex.model.channel import Channel
from holodex.model.channel_video import ChannelVideoInfo
from holodex.model.channels import LiteChannel

from .env_config import HOLODEX_API_KEY, HOLODEX_PARALLEL_COUNT

_logger = logging.getLogger(__name__)
HOLODEX_SEMAPHORE = asyncio.Semaphore(HOLODEX_PARALLEL_COUNT)


async def download_channel_video_info(channel_ids: Iterable[str]) -> AsyncIterator[ChannelVideoInfo]:
    limit = 50
    async with HOLODEX_SEMAPHORE, HolodexClient(key=HOLODEX_API_KEY) as client:
        for channel_id in channel_ids:
            for video_type in ["videos", "collabs"]:
                offset = 0
                while True:
                    channel_video = await client.videos_from_channel(
                        channel_id=channel_id,
                        type=video_type,
                        include=["mentions", "description"],
                        limit=limit,
                        offset=offset,
                    )

                    for video_info in channel_video.contents:
                        yield video_info

                    offset += len(channel_video.contents)
                    if len(channel_video.contents) < limit:
                        break


async def download_org_channels(org: str) -> AsyncIterator[LiteChannel]:
    limit = 50
    async with HOLODEX_SEMAPHORE, HolodexClient(key=HOLODEX_API_KEY) as client:
        offset = 0
        while True:
            # noinspection PyTypeChecker
            channels = await client.channels(
                type="vtuber",
                org=org,  # "All Vtubers", "Hololive", "Nijisanji", "Independents"
                limit=limit,
                offset=offset,
            )
            for lite_channel in channels:
                yield lite_channel

            offset += len(channels)
            if len(channels) < limit:
                break


async def download_channels(channel_ids: Iterable[str]) -> AsyncIterator[Channel]:
    async with HOLODEX_SEMAPHORE, HolodexClient(key=HOLODEX_API_KEY) as client:
        for channel_id in channel_ids:
            try:
                yield await client.channel(channel_id)
            except Exception:
                _logger.exception("Channel info could not be fetched: %s", channel_id)
