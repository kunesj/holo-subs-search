from __future__ import annotations

import asyncio
import datetime
import functools
import hashlib
import json
import types
import typing
from typing import Annotated, Any, Callable, ClassVar, Iterator, Literal, Mapping, TypeVar, Union

import annotated_types

T = TypeVar("T")

NoneType = types.NoneType
UnionType = types.UnionType
LiteralType = type(Literal[None])
ClassVarType = type(ClassVar[None])

AnyDateTime = Annotated[datetime.datetime, ...]
NaiveDateTime = Annotated[datetime.datetime, annotated_types.Timezone(None)]
AwareDateTime = Annotated[datetime.datetime, annotated_types.Timezone(...)]


class UndefinedType:
    pass


Undefined = UndefinedType()


def is_async_callable(obj: Union[Callable, Any]) -> bool:
    """
    Better than inspect.iscoroutinefunction, because it also supports objects with `async def __call__():`.
    Copy of `starlette._utils.is_async_callable`.
    """
    while isinstance(obj, functools.partial):
        obj = obj.func

    # noinspection PyUnresolvedReferences
    return asyncio.iscoroutinefunction(obj) or (callable(obj) and asyncio.iscoroutinefunction(obj.__call__))


def _json_dumps_default(obj: Any) -> Any:
    if isinstance(obj, (set, tuple)):
        return [*obj]
    elif isinstance(obj, types.MappingProxyType):
        return {**obj}
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def json_dumps(obj) -> str:
    return json.dumps(obj, default=_json_dumps_default, sort_keys=True)


def get_checksum(data: bytes) -> str:
    """Computes checksum of binary data."""
    return hashlib.sha1(data).hexdigest()


def type_origin_is_union(type_origin: Any) -> bool:
    return bool(type_origin is Union or (isinstance(type_origin, type) and issubclass(type_origin, UnionType)))


def type_origin_is_literal(type_origin: Any) -> bool:
    return bool(type_origin is Literal or (isinstance(type_origin, type) and issubclass(type_origin, LiteralType)))


def type_origin_is_classvar(type_origin: Any) -> bool:
    return type_origin is ClassVar


# noinspection PyUnresolvedReferences
strip_annotations: Callable[[Any], Any] = typing._strip_annotations


def iter_typing_types(typing_: Any) -> Iterator[tuple[type[Any], ...]]:
    """
    Yields tuples of all types contained in typing.
    Can return duplicate values. Eq. `tuple[str, str]` will return `(tuple, str)` twice.
    """
    stack = [([], strip_annotations(typing_))]
    while stack:
        parents, frag = stack.pop()
        # list[...]   ->   <class 'list'>
        # Literal[...]   ->   typing.Literal
        # str | None   ->   <class 'types.UnionType'>
        # Union[str, None]   ->   typing.Union
        frag_origin = typing.get_origin(frag)
        # list[int, str]   ->   <class 'int'>, <class 'str'>
        # Literal["a", 1]   ->   'a', 1
        frag_args = typing.get_args(frag)
        # str   ->   True
        # Union[str, None]   ->   False
        # Union[str]   ->   True !!! makes sense since it resolves to just `str`
        # str | None   ->   False
        # list[str]   ->   False
        # Literal["a", 1]   ->   False
        frag_is_type = isinstance(frag, type)
        frag_origin_is_type = isinstance(frag_origin, type)

        # raw type

        if frag_is_type and frag_origin:
            raise ValueError("Non-parsable typing fragment", frag)

        elif frag_is_type:
            yield *parents, frag

        # Union, Literal, ClassVar

        elif type_origin_is_union(frag_origin):
            stack += [(parents, arg) for arg in frag_args]

        elif type_origin_is_literal(frag_origin):
            stack += [(parents, arg) for arg in frag_args]

        elif type_origin_is_classvar(frag_origin):
            stack += [(parents, arg) for arg in frag_args]

        # parametrized type

        elif frag_origin and not frag_origin_is_type:
            raise ValueError("Non-parsable typing fragment", frag)

        elif frag_origin and issubclass(frag_origin, Mapping):
            # we have two types (key and value), so we can't continue deeper
            yield *parents, frag_origin

        elif frag_origin and issubclass(frag_origin, Callable):
            if parents:
                yield tuple(parents)

        elif frag_origin and (not frag_args or all(x is ... for x in frag_args)):
            # somehow parametrized without parameters or list[...]
            yield *parents, frag_origin

        elif frag_origin:
            stack += [([*parents, frag_origin], arg) for arg in frag_args]

        # instance

        elif frag is ...:
            continue

        else:
            yield *parents, type(frag)


def with_semaphore(arg: Union[Callable, asyncio.Semaphore, int] = 1) -> Callable:
    """
    Decorator that sets limits concurrent call to wrapped function
    """
    if isinstance(arg, asyncio.Semaphore):
        _fcn = None
        semaphore = arg
    elif isinstance(arg, int):
        _fcn = None
        semaphore = asyncio.Semaphore(arg)
    elif is_async_callable(arg):
        _fcn = arg
        semaphore = asyncio.Semaphore(1)
    else:
        raise ValueError(arg)

    def wrapper(fcn: Callable) -> Callable:
        if not is_async_callable(fcn):
            raise ValueError(fcn)

        @functools.wraps(fcn)
        async def wrapped(*args, **kwargs):
            async with semaphore:
                return await fcn(*args, **kwargs)

        return wrapped

    return wrapper(_fcn) if _fcn else wrapper
