import asyncio
import datetime
import hashlib
import json
from types import MappingProxyType
from typing import Annotated, Any, AsyncIterator, Iterator, TypeVar

import annotated_types

T = TypeVar("T")

AnyDateTime = Annotated[datetime.datetime, ...]
NaiveDateTime = Annotated[datetime.datetime, annotated_types.Timezone(None)]
AwareDateTime = Annotated[datetime.datetime, annotated_types.Timezone(...)]


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


def _json_dumps_default(obj: Any) -> Any:
    if isinstance(obj, (set, tuple)):
        return [*obj]
    elif isinstance(obj, MappingProxyType):
        return {**obj}
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def json_dumps(obj) -> str:
    return json.dumps(obj, default=_json_dumps_default, sort_keys=True)


def get_checksum(data: bytes) -> str:
    """Computes checksum of binary data."""
    return hashlib.sha1(data).hexdigest()
