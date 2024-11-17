#!/usr/bin/env python3.11

import bisect
import dataclasses
import datetime
import re
from typing import Self

from .sub_parser import Iterator, SubFile, SubLine


@dataclasses.dataclass
class IndexedLine:
    start: int
    end: int
    line_index: int


@dataclasses.dataclass
class SearchableSubFile:
    """
    - join all strings into one long string (new lines replaced by spaces)
    - remember indexes of where every part starts and ends
    - find indexes of all matches
    - convert string indexes into lines indexes
    """

    sub_file: SubFile
    content: str
    indexed: list[IndexedLine]  # must be sorted

    @property
    def lines(self) -> list[SubLine]:
        return self.sub_file.lines

    @classmethod
    def from_sub_file(cls: type[Self], sub_file: SubFile) -> Self:
        content_parts = []
        indexed_lines = []
        last_index = 0

        for idx, sub_line in enumerate(sub_file.lines):
            line_content = sub_line.content.replace("\n", " ")
            if not line_content:
                continue

            if last_index != 0:
                line_content = " " + line_content

            content_parts.append(line_content)
            indexed_lines.append(IndexedLine(start=last_index, end=last_index + len(line_content), line_index=idx))
            last_index += len(line_content)

        return cls(
            sub_file=sub_file,
            content="".join(content_parts),
            indexed=indexed_lines,
        )

    def match_to_line_indexes(self, match_start: int, match_end: int) -> list[int]:
        # uses binary search for speed

        # self.indexed[:_idx] where all "x.start <= match_start"
        _idx = bisect.bisect_right(self.indexed, match_start, key=lambda x: x.start)
        lines_start_idx = max(_idx - 1, 0)

        # self.indexed[:_idx] where all "x.end < match_end"
        _idx = bisect.bisect_left(self.indexed, match_end, lo=lines_start_idx, key=lambda x: x.end)
        lines_stop_idx = min(_idx + 1, len(self.indexed))

        indexed_lines = self.indexed[lines_start_idx:lines_stop_idx]
        if not indexed_lines:
            raise RuntimeError("No indexed lines found, something is wrong")

        return [x.line_index for x in indexed_lines]

    def search_exact(self, value: str, case_sensitive: bool = False) -> Iterator[list[int]]:
        if not value:
            return

        if case_sensitive:
            content = self.content
        else:
            content = self.content.lower()
            value = value.lower()

        offset = 0
        while idx := content[offset:].find(value):
            if idx < 0:
                return

            match_start = offset + idx
            match_end = match_start + len(value)

            if offset == match_end:
                break  # empty match, braking to prevent infinite search

            yield self.match_to_line_indexes(match_start=match_start, match_end=match_end)
            offset = match_end

    def search_regex(self, value: str, case_sensitive: bool = False) -> Iterator[list[int]]:
        if not value:
            return

        flags = re.NOFLAG if case_sensitive else re.IGNORECASE
        offset = 0

        while match := re.search(value, self.content[offset:], flags=flags):
            match_start = offset + match.start()
            match_end = offset + match.end()

            if offset == match_end:
                break  # empty match, braking to prevent infinite search

            yield self.match_to_line_indexes(match_start=match_start, match_end=match_end)
            offset = match_end

    def search(self, value: str, regex: bool = False, case_sensitive: bool = False) -> Iterator[list[int]]:
        if regex:
            for indexes in self.search_regex(value, case_sensitive=case_sensitive):
                yield indexes
        else:
            for indexes in self.search_exact(value, case_sensitive=case_sensitive):
                yield indexes

    def index_to_past_index(self, index: int, delta: datetime.timedelta) -> int:
        """
        Returns index of line that starts X amount of time before the line with provided index.
        Useful for adding relevant lines to search results.
        """
        if delta.total_seconds() < 0:
            raise ValueError(delta)

        min_start = self.lines[index].start - delta
        while index > 0:
            if self.lines[index - 1].start >= min_start:
                index -= 1
            else:
                break

        return index

    def index_to_future_index(self, index: int, delta: datetime.timedelta) -> int:
        """
        Returns index of line that starts X amount of time after the line with provided index.
        Useful for adding relevant lines to search results.
        """
        if delta.total_seconds() < 0:
            raise ValueError(delta)

        max_start = self.lines[index].start + delta
        while index < len(self.lines):
            if self.lines[index + 1].start <= max_start:
                index += 1
            else:
                break

        return index
