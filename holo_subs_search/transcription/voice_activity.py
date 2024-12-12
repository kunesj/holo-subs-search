from __future__ import annotations

import functools
import logging
from collections import namedtuple
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

if TYPE_CHECKING:
    from ..diarization import Diarization

_logger = logging.getLogger(__name__)


class VoiceActivityChunk(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True,
        validate_default=True,
        validate_return=True,
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    start: float
    end: float

    @model_validator(mode="after")
    def _check_start_end(self) -> VoiceActivityChunk:
        if self.start >= self.end:
            raise ValueError("AudioChunk start must be before end", self.start, self.end)
        return self

    @computed_field
    @functools.cached_property
    def duration(self) -> float:
        return self.end - self.start


def diarization_to_voice_activity(
    dia: Diarization,
    *,
    padding: float = 0.2,
    min_duration: float = 0.1,
    max_duration: float = 30.0,
    max_gap: float = 3.0,
) -> list[VoiceActivityChunk]:
    """
    - overlapping diarization segments must be merged

    For use with Whisper:
    - silent time must be excluded
    - close chunks should be merged to make the transcription flow better.
    - chunks should not be longer than 30s, because that's internal chunk size of whisper.
    - there should be a very tiny silent gap before and after speech, to have some buffer in case of timestamp errors
    - very tiny segments should be excluded, as they shouldn't contain any real words (?)
    """
    max_duration -= 2 * padding
    if max_gap < padding:
        raise ValueError("max_gap must be larger than padding")

    chunks = [VoiceActivityChunk(start=x.start, end=x.end) for x in dia.diarization]

    # sort and merge overlapping chunks
    chunks = _merge_overlapping_chunks(chunks)

    # merge close chunks
    chunks = _merge_close_chunks(chunks, max_duration=max_duration, max_gap=max_gap)

    # exclude tiny chunks that probably don't contain any speech
    chunks = [x for x in chunks if x.duration >= min_duration]

    # add padding to chunks
    chunks = _pad_chunks(chunks, padding=padding)

    return chunks


def _merge_overlapping_chunks(chunks: list[VoiceActivityChunk]) -> list[VoiceActivityChunk]:
    """
    Sorts and merges overlapping chunks
    """
    new_chunks = []

    start = None
    end = None

    for chunk in sorted(chunks, key=lambda x: x.start):
        if start is None:  # first chunk
            start = chunk.start
            end = chunk.end
        elif start <= chunk.start <= end:  # overlapping
            end = max(end, chunk.end)
        else:  # not overlapping
            new_chunks.append(VoiceActivityChunk(start=start, end=end))
            start = chunk.start
            end = chunk.end

    if start is not None:
        new_chunks.append(VoiceActivityChunk(start=start, end=end))

    return new_chunks


def _merge_close_chunks(
    chunks: list[VoiceActivityChunk],
    *,
    max_duration: float,
    max_gap: float,
) -> list[VoiceActivityChunk]:
    """
    Merges close chunks.
    - chunks must be sorted and must not overlap
    - starts merging from the smallest gaps first
    - max_gap should be less than 1s?: https://github.com/ggerganov/whisper.cpp/issues/1724
    """
    if len(chunks) <= 1:
        return chunks

    GapAndDuration = namedtuple("GapAndDuration", ["gap", "duration"])
    results = [*chunks]

    def _get_gap(idx) -> GapAndDuration:
        return GapAndDuration(
            gap=results[idx + 1].start - results[idx].end,
            duration=results[idx + 1].end - results[idx].start,
        )

    gaps = [_get_gap(idx) for idx in range(len(results) - 1)]
    while len(results) >= 2:
        if usable_gaps := [x for x in gaps if (x.gap <= max_gap and x.duration <= max_duration)]:
            merge_gap = min(usable_gaps, key=lambda x: x.gap)
            merge_idx = gaps.index(merge_gap)
        else:
            break

        results[merge_idx : merge_idx + 2] = [
            VoiceActivityChunk(start=results[merge_idx].start, end=results[merge_idx + 1].end)
        ]

        if merge_idx - 1 >= 0:
            gaps[merge_idx - 1] = _get_gap(merge_idx - 1)

        if merge_idx < len(gaps) - 1:
            gaps[merge_idx : merge_idx + 2] = [_get_gap(merge_idx)]
        else:
            gaps[merge_idx : merge_idx + 2] = []

    return results


def _pad_chunks(chunks: list[VoiceActivityChunk], *, padding: float) -> list[VoiceActivityChunk]:
    """
    Expands chunks to contain small amount of silence before and after them.
    - This is to prevent potential issues caused by potentially imprecise timestamps.
    - chunks must be sorted and must not overlap
    """
    results = []

    for idx, chunk in enumerate(chunks):
        if idx == 0:
            min_start = 0.0
        else:
            min_start = chunk.start - ((chunk.start - chunks[idx - 1].end) / 2)

        if idx >= len(chunks) - 1:
            max_end = chunk.end + padding
        else:
            max_end = chunk.end + ((chunks[idx + 1].start - chunk.end) / 2)

        results.append(
            VoiceActivityChunk(
                start=max(chunk.start - padding, min_start),
                end=min(chunk.end + padding, max_end),
            )
        )

    return results
