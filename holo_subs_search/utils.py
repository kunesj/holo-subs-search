#!/usr/bin/env python3.11

import asyncio
from typing import AsyncIterator, Iterator, TypeVar

T = TypeVar("T")


def iter_over_async(ait: AsyncIterator[T]) -> Iterator[T]:
    with asyncio.Runner() as runner:
        loop = runner.get_loop()
        ait = ait.__aiter__()

        # helper async fn that just gets the next element
        # from the async iterator
        async def get_next():
            try:
                return False, await ait.__anext__()
            except StopAsyncIteration:
                return True, None

        # actual sync iterator (implemented using a generator)
        while True:
            done, obj = loop.run_until_complete(get_next())
            if done:
                break
            yield obj
