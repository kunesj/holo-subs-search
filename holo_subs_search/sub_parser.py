#!/usr/bin/env python3.11

import dataclasses
import datetime
import pathlib
from typing import Any, Iterator, Self

import srt


@dataclasses.dataclass
class SubLine:
    start: datetime.timedelta
    end: datetime.timedelta
    content: str

    @classmethod
    def from_json(cls: type[Self], value: list) -> Self:
        return cls(
            start=datetime.timedelta(seconds=value[0]),
            end=datetime.timedelta(seconds=value[1]),
            content=value[2],
        )

    def to_json(self) -> list:  # [start, end, content]
        """
        Returns as `[start, end, content]`.
        Not a dict to lower the amount of redundant data when dumping a lot of lines to JSON.
        """
        return [self.start.total_seconds(), self.end.total_seconds(), self.content]


@dataclasses.dataclass
class SubFile:
    timestamp: float
    source: str
    lang: str
    lines: list[SubLine]

    @classmethod
    def from_json(cls: type[Self], value: dict[str, Any]) -> Self:
        return cls(
            timestamp=value["timestamp"],
            source=value["source"],
            lang=value["lang"],
            lines=[SubLine.from_json(x) for x in value["lines"]],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "lang": self.lang,
            "lines": [line.to_json() for line in self.lines],
        }


def parse_srt_file(source: str | pathlib.Path) -> Iterator[SubLine]:
    """
    Parses automatic YouTube subtitles.
    - merges/splits duplicated lines
    - removes some unneeded special characters
    - generated lines might be overlapping
    """
    if isinstance(source, pathlib.Path):
        source = source.read_text()
    elif not isinstance(source, str):
        raise TypeError(source)

    unfinished = []
    for sub in srt.parse(source):
        # split content into separate lines

        raw_lines = []

        for raw_line in sub.content.splitlines():
            raw_line = raw_line.replace("[\\h__\\h]", "")
            raw_line = " ".join(raw_line.split())
            if raw_line:
                raw_lines.append(raw_line)

        if not raw_lines:
            continue  # empty subtitle

        # remove finished lines

        while (
            unfinished
            and raw_lines
            and (
                # does not have same content
                unfinished[0].content != raw_lines[0]
                # is not continuation of previous line
                or unfinished[0].end != sub.start
            )
        ):
            yield unfinished.pop(0)

        # update end time of current lines

        while (
            unfinished
            and raw_lines
            # has the same content
            and unfinished[0].content == raw_lines[0]
            # is continuation of previous line
            and unfinished[0].end == sub.start
        ):
            raw_lines.pop(0)
            unfinished[0].end = sub.end

        # add new lines

        unfinished += [SubLine(start=sub.start, end=sub.end, content=raw_line) for raw_line in raw_lines]

    for sub_line in unfinished:
        yield sub_line
