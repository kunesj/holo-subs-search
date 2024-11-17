#!/usr/bin/env python3.11

import bisect
import dataclasses
import re
from typing import Self

from .sub_parser import Iterator, SubFile


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
    indexed: list[IndexedLine]

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
        lines_start_idx = bisect.bisect_left(self.indexed, match_start, key=lambda x: x.start)
        lines_stop_idx = bisect.bisect_right(self.indexed, match_end, lo=lines_start_idx, key=lambda x: x.end)

        indexed_lines = self.indexed[lines_start_idx : lines_stop_idx + 1]
        if not indexed_lines:
            raise RuntimeError("No indexed lines found, something is wrong")

        return [x.line_index for x in indexed_lines]

    def search_exact(self, value: str) -> Iterator[list[int]]:
        if not value:
            return

        offset = 0
        while idx := self.content[offset:].find(value):
            if idx < 0:
                return

            match_start = offset + idx
            match_end = offset + idx

            if offset == match_end:
                break  # empty match, braking to prevent infinite search

            yield self.match_to_line_indexes(match_start=match_start, match_end=match_end)
            offset = match_end

    def search_regex(self, value: str) -> Iterator[list[int]]:
        if not value:
            return

        offset = 0
        while match := re.search(value, self.content[offset:], flags=re.IGNORECASE):
            match_start = offset + match.start()
            match_end = offset + match.end()

            if offset == match_end:
                break  # empty match, braking to prevent infinite search

            yield self.match_to_line_indexes(match_start=match_start, match_end=match_end)
            offset = match_end

    def search(self, value: str, regex: bool = False) -> Iterator[list[int]]:
        if regex:
            for indexes in self.search_regex(value):
                yield indexes
        else:
            for indexes in self.search_exact(value):
                yield indexes
