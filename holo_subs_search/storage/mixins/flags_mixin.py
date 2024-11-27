#!/usr/bin/env python3.11

from __future__ import annotations

import abc
import logging
from typing import Any

import yt_dlp

from .metadata_mixin import MetadataMixin

_logger = logging.getLogger(__name__)


class Flags:
    # Download only videos that are collabs with other channels (refresh of video list is skipped)
    MENTIONS_ONLY = "mentions-only"

    # Don't refresh Holodex info
    HOLODEX_PRESERVE = "holodex-preserve"

    # Don't refresh YouTube info
    YOUTUBE_PRESERVE = "youtube-preserve"
    # content is accessible only by channel owner
    YOUTUBE_PRIVATE = "youtube-private"
    # content has been deleted, or it never existed in the first place
    YOUTUBE_UNAVAILABLE = "youtube-unavailable"
    # content is accessible only by channel members
    YOUTUBE_MEMBERSHIP = "youtube-membership"
    # content is accessible only by signed in accounts with confirmed age
    YOUTUBE_AGE_RESTRICTED = "youtube-age-restricted"

    # flags of SubtitleItem objects
    SUBTITLE_TRANSCRIPTION = "transcription"
    SUBTITLE_TRANSLATION = "translation"

    @classmethod
    def from_yt_dlp_error(cls, e: Exception) -> str | None:
        if not isinstance(e, yt_dlp.utils.DownloadError):
            return None

        if any(x in e.msg for x in ("members-only", "This video is available to this channel's members")):
            return Flags.YOUTUBE_MEMBERSHIP
        elif any(x in e.msg for x in ("Private video", "This video is private")):
            return Flags.YOUTUBE_PRIVATE
        elif "Video unavailable" in e.msg:
            return Flags.YOUTUBE_UNAVAILABLE
        elif "Sign in to confirm your age" in e.msg:
            return Flags.YOUTUBE_AGE_RESTRICTED

        return None


class FlagsMixin(MetadataMixin, abc.ABC):
    @property
    def flags(self) -> frozenset[str]:
        return frozenset(self.metadata.get("flags", []))

    @flags.setter
    def flags(self, value: set[str]) -> None:
        self.metadata = dict(self.metadata, flags=list(value))

    @classmethod
    def build_metadata(cls, *, flags: set[str] | None = None, **kwargs) -> dict[str, Any]:
        return super().build_metadata(**kwargs) | {"flags": set() if flags is None else set(flags)}
