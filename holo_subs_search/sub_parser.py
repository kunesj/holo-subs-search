#!/usr/bin/env python3.11

import dataclasses
import datetime
from typing import Iterator

import srt


@dataclasses.dataclass
class SubLine:
    start: datetime.timedelta
    end: datetime.timedelta
    content: str

    def to_json(self) -> dict:
        return {"start": self.start.total_seconds(), "end": self.end.total_seconds(), "content": self.content}


def parse_srt_file(file_path: str) -> Iterator[SubLine]:
    """
    Parses automatic YouTube subtitles.
    - merges/splits duplicated lines
    - removes some unneeded special characters
    - generated lines might be overlapping
    """
    with open(file_path, "r") as f:
        srt_data = f.read()

    unfinished = []
    for sub in srt.parse(srt_data):
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
