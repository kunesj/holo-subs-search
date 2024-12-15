from __future__ import annotations

import contextlib
import functools
import io
import logging
import os
from collections.abc import Iterator
from contextvars import ContextVar, copy_context
from typing import Any, Awaitable, Callable, TypeVar

from .utils import Undefined, UndefinedType, is_async_callable

T = TypeVar("T")
LogContextType = list[str]

_logger = logging.getLogger(__name__)

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, _NOTHING, DEFAULT = range(10)
# The background is set with 40 plus the number of the color, and the foreground with 30
# These are the sequences needed to get colored output
RESET_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"
BOLD_SEQ = "\033[1m"
COLOR_PATTERN = "%s%s%%s%s" % (COLOR_SEQ, COLOR_SEQ, RESET_SEQ)
LEVEL_COLOR_MAPPING = {
    logging.DEBUG: (BLUE, DEFAULT),
    logging.INFO: (GREEN, DEFAULT),
    logging.WARNING: (YELLOW, DEFAULT),
    logging.ERROR: (RED, DEFAULT),
    logging.CRITICAL: (WHITE, RED),
}

LOGGER_FORMAT = "%(asctime)s %(pid)s %(levelname)s <%(context)s> %(name)s: %(message)s"
LOGGING_VALUES_CTX_VAR: ContextVar[tuple[LogContextType]] = ContextVar("logging_values", default=([],))


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        """Extended"""
        (context,) = LOGGING_VALUES_CTX_VAR.get()
        record.pid = os.getpid()
        record.context = ",".join(context)
        return super().format(record)


class ColoredFormatter(PlainFormatter):
    def format(self, record: logging.LogRecord) -> str:
        """Extended to add colors"""
        # noinspection PyTypeChecker
        fg_color, bg_color = LEVEL_COLOR_MAPPING.get(record.levelno, (GREEN, DEFAULT))
        record.levelname = COLOR_PATTERN % (30 + fg_color, 40 + bg_color, record.levelname)
        return super().format(record)


def setup_logging(log_level: int, log_type: str = "colored") -> None:
    """
    Configures logging
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # add handler

    handler = logging.StreamHandler()

    try:
        is_tty = hasattr(handler.stream, "fileno") and os.isatty(handler.stream.fileno())
    except io.UnsupportedOperation:
        is_tty = False

    match log_type:
        case "plain":
            formatter = PlainFormatter(LOGGER_FORMAT)
        case "colored" if is_tty:
            _logger.debug("log_type='colored' is not supported in TTY, switching to 'plain'")
            formatter = PlainFormatter(LOGGER_FORMAT)
        case "colored":
            formatter = ColoredFormatter(LOGGER_FORMAT)
        case _:
            _logger.warning("Unexpected log_type=%r, switching to 'plain'", log_type)
            formatter = PlainFormatter(LOGGER_FORMAT)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # set logging levels

    root_logger.setLevel(log_level)
    logging.getLogger("openai").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("httpcore").setLevel(logging.INFO)


class LoggingValues:
    """
    Class that manages LOGGING_VALUES_CTX_VAR that is used to display backend and context in logs.
    Backend values are always replaced if set, and context values are merged.
    """

    def __init__(
        self,
        *,
        context: LogContextType | UndefinedType = Undefined,
    ) -> None:
        # replace undefined values with current values

        (current_context,) = LOGGING_VALUES_CTX_VAR.get()

        if context is Undefined:
            context = current_context
        else:
            # contexts are always merged
            context = [*current_context, *context]
            context = sorted(set(context), key=context.index)

        self.context = context

    @contextlib.contextmanager
    def manager(self) -> Iterator[None]:
        token = LOGGING_VALUES_CTX_VAR.set((self.context,))
        try:
            yield
        finally:
            LOGGING_VALUES_CTX_VAR.reset(token)

    def run(self, _fcn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """
        Runs chain of sync functions with these logging values
        """
        if is_async_callable(_fcn):
            raise ValueError("Function must not be async")

        with self.manager():
            return copy_context().run(_fcn, *args, **kwargs)

    async def async_run(self, _fcn: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any) -> T:
        """
        Runs chain of async functions with these logging values
        """
        if not is_async_callable(_fcn):
            raise ValueError("Function must be async")

        # async methods automatically copy context, so we don't have to do it manually
        with self.manager():
            return await _fcn(*args, **kwargs)


def logging_with_values(
    *,
    get_context: Callable[..., list[str]] | None = None,
) -> Callable:
    """
    Decorator that sets logging values
    """

    def _get_logging_values_kwargs(*args, **kwargs) -> dict:
        result = {}

        if get_context is not None:
            result["context"] = get_context(*args, **kwargs)

        return result

    def wrapper(fcn: Callable) -> Callable:
        if is_async_callable(fcn):

            @functools.wraps(fcn)
            async def wrapped(*args, **kwargs):
                log_values = LoggingValues(**_get_logging_values_kwargs(*args, **kwargs))
                return await log_values.async_run(fcn, *args, **kwargs)

        else:

            @functools.wraps(fcn)
            def wrapped(*args, **kwargs):
                log_values = LoggingValues(**_get_logging_values_kwargs(*args, **kwargs))
                return log_values.run(fcn, *args, **kwargs)

        return wrapped

    return wrapper
