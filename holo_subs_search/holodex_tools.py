from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any, AsyncIterator, Iterable, Literal, Optional, Self

import aiohttp
from holodex.client import HolodexClient
from holodex.model.channel import Channel
from holodex.model.channel_video import ChannelVideoInfo
from holodex.model.channels import LiteChannel

from .env_config import HOLODEX_API_KEY, HOLODEX_PARALLEL_COUNT

_logger = logging.getLogger(__name__)


class BetterHolodexClient(HolodexClient):
    HOLODEX_SEMAPHORE = asyncio.Semaphore(HOLODEX_PARALLEL_COUNT)
    MAX_RETRY = 7  # 128 seconds

    async def __aenter__(self) -> Self:
        await self.HOLODEX_SEMAPHORE.acquire()
        return await super().__aenter__()

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        try:
            return await super().__aexit__(exc_type=exc_type, exc_val=exc_val, exc_tb=exc_tb)
        finally:
            self.HOLODEX_SEMAPHORE.release()

    async def request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        **kwargs: Any,
    ) -> Any:
        if not self.session:
            self.session = aiohttp.ClientSession()

        http_429_count = 0
        while True:
            async with self.session.request(
                method,
                self.BASE_URL + endpoint,
                headers=self.headers,
                **kwargs,
            ) as response:
                if response.status == 429 and http_429_count > self.MAX_RETRY:
                    raise
                elif response.status == 429:
                    _logger.info("Got HTTP 429, will retry in %s seconds", 2**http_429_count)
                    await asyncio.sleep(2**http_429_count)
                    http_429_count += 1
                    continue

                response.raise_for_status()
                return await response.json()


async def download_channel_video_info(channel_ids: Iterable[str]) -> AsyncIterator[ChannelVideoInfo]:
    limit = 50
    async with BetterHolodexClient(key=HOLODEX_API_KEY) as client:
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
    async with BetterHolodexClient(key=HOLODEX_API_KEY) as client:
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
                # we want the full channel info, the lite channel is missing some important information
                yield await client.channel(lite_channel.id)

            offset += len(channels)
            if len(channels) < limit:
                break


async def download_channels(channel_ids: Iterable[str]) -> AsyncIterator[Channel]:
    async with BetterHolodexClient(key=HOLODEX_API_KEY) as client:
        for channel_id in channel_ids:
            try:
                yield await client.channel(channel_id)
            except Exception:
                _logger.exception("Channel info could not be fetched: %s", channel_id)
