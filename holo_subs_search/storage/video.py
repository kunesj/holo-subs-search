#!/usr/bin/env python3.11

from __future__ import annotations

import datetime
import json
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Self

import yt_dlp
from holodex.model.channel_video import ChannelVideoInfo as HolodexChannelVideoInfo

from .. import whisper_tools, ydl_tools
from ..utils import AwareDateTime, json_dumps
from .mixins.content_mixin import AudioItem, ContentMixin, SubtitleItem
from .mixins.flags_mixin import Flags, FlagsMixin
from .mixins.holodex_mixin import HolodexMixin
from .record import Record

if TYPE_CHECKING:
    from .storage import Storage

SubtitlesState = Literal["missing", "garbage"]

_logger = logging.getLogger(__name__)


class VideoRecord(ContentMixin, HolodexMixin, FlagsMixin, Record):
    model_name = "video"

    # Fields

    @property
    def channel_id(self) -> str:
        return self.metadata["channel_id"]

    @property
    def youtube_subtitles(self) -> MappingProxyType[str, SubtitlesState]:
        return MappingProxyType(self.metadata.get("youtube_subtitles", {}))

    @youtube_subtitles.setter
    def youtube_subtitles(self, value: dict[str, SubtitlesState]) -> None:
        self.metadata = dict(self.metadata, youtube_subtitles=value)

    # Computed properties

    @property
    def published_at(self) -> AwareDateTime | None:
        if self.holodex_info and (raw := self.holodex_info.get("published_at")):
            value = datetime.datetime.fromisoformat(raw)
        elif self.holodex_info and (raw := self.holodex_info.get("available_at")):
            value = datetime.datetime.fromisoformat(raw)
        elif self.youtube_info and (raw := self.youtube_info.get("upload_date")):
            value = datetime.datetime.fromisoformat(raw)
        elif self.youtube_info and (raw := self.youtube_info.get("release_date")):
            value = datetime.datetime.fromisoformat(raw)
        else:
            value = None

        if value and not value.tzinfo:
            value = value.replace(tzinfo=datetime.timezone.utc)

        return value

    @property
    def title(self) -> str | None:
        if self.holodex_info and (title := self.holodex_info.get("title")):
            return title
        elif self.youtube_info and (title := self.youtube_info.get("title")):
            return title
        return None

    @property
    def youtube_url(self) -> str | None:
        """Implemented"""
        if self.youtube_id:
            return f"https://www.youtube.com/watch?v={self.youtube_id}"
        return None

    @property
    def holodex_url(self) -> str | None:
        """Implemented"""
        if self.holodex_id:
            return f"https://holodex.net/watch/{self.holodex_id}"
        return None

    # Methods

    @classmethod
    def build_metadata(cls, *, channel_id: str | None = None, **kwargs) -> dict[str, Any]:
        if not channel_id:
            raise ValueError("channel_id is required")
        return super().build_metadata(**kwargs) | {"channel_id": channel_id}

    @classmethod
    def from_holodex(
        cls: type[Self],
        *,
        storage: Storage,
        value: HolodexChannelVideoInfo,
        default_metadata: dict[str, Any] | None = None,
        update_holodex_info: bool = True,
    ) -> Self:
        holodex_info = json.loads(json_dumps(value._response))
        record = cls.from_holodex_id(storage=storage, id=value.id)

        if not record.exists():
            channel = ChannelRecord.from_holodex(
                storage=storage,
                value=value.channel,
                default_metadata={"flags": {Flags.MENTIONS_ONLY}},
                update_holodex_info=False,
            )

            default_metadata = (default_metadata or {}) | {"channel_id": channel.id}
            metadata = cls.build_metadata(**default_metadata)

            record.create(metadata)
            record.holodex_info = holodex_info

        elif update_holodex_info or not record.holodex_info:
            record.holodex_info = holodex_info

        return record

    def update_gitignore(self) -> None:
        gitignore_path = self.record_path / ".gitignore"
        if Flags.YOUTUBE_MEMBERSHIP in self.flags and not gitignore_path.exists():
            gitignore_path.write_text("/content\n")
        elif Flags.YOUTUBE_MEMBERSHIP not in self.flags and gitignore_path.exists():
            gitignore_path.unlink()

    # Youtube

    def fetch_youtube(
        self,
        download_subtitles: list[str] | None = None,
        download_audio: bool = False,
        cookies_from_browser: str | None = None,
    ) -> None:
        _logger.info("Fetching Youtube subtitles for video %s - %s", self.id, self.published_at)

        try:
            for name, file_path in ydl_tools.download_video(
                video_id=self.youtube_id,
                download_subtitles=download_subtitles,
                download_audio=download_audio,
                cookies_from_browser=cookies_from_browser,
            ):
                if name == "info.json":
                    if not self.youtube_info or Flags.YOUTUBE_PRESERVE not in self.flags:
                        with open(file_path, "r") as f:
                            info = json.loads(f.read())

                            # trim down the info to only useful data
                            for key in ["formats", "automatic_captions", "subtitles", "thumbnails"]:
                                info.pop(key, None)

                            self.youtube_info = info

                elif any(name.endswith(f".{x}") for x in whisper_tools.WHISPER_AUDIO_FORMATS):
                    with open(file_path, "rb") as f:
                        content_id = f"youtube.audio.{name}/".replace(".", "-")
                        item = AudioItem(path=self.content_path / content_id)

                        metadata = AudioItem.build_metadata(source="youtube", audio_file=name)
                        item.create(metadata)
                        item.audio_path.write_bytes(f.read())

                elif name.endswith(".srt"):
                    with open(file_path, "r") as f:
                        content_id = f"youtube.subtitle.{name}/".replace(".", "-")  # youtube.en.srt
                        item = SubtitleItem(path=self.content_path / content_id)
                        flags = set()

                        sub_type, lang, _ = name.split(".", maxsplit=2)

                        if sub_type == ydl_tools.PROPER_SUBS:
                            pass
                        elif sub_type == ydl_tools.TRANSCRIPTION_SUBS:
                            flags.add(Flags.SUBTITLE_TRANSCRIPTION)
                        elif sub_type == ydl_tools.TRANSLATION_SUBS:
                            flags.add(Flags.SUBTITLE_TRANSLATION)
                        else:
                            raise ValueError("Unexpected subtitle type", sub_type)

                        metadata = SubtitleItem.build_metadata(
                            source="youtube",
                            lang=lang,
                            flags=flags,
                            subtitle_file=name,
                        )

                        item.create(metadata)
                        item.subtitle_path.write_text(f.read())

                else:
                    _logger.warning("Fetched unexpected file: %s", name)

        except yt_dlp.utils.DownloadError as e:
            match flag := Flags.from_yt_dlp_error(e):
                case Flags.YOUTUBE_MEMBERSHIP if Flags.YOUTUBE_MEMBERSHIP not in self.flags:
                    _logger.error("Unexpected members-only download error, marking video as members-only: %s", e)
                case Flags.YOUTUBE_PRIVATE:
                    _logger.error("Private video, subtitle fetch will be disabled: %s", e)
                case Flags.YOUTUBE_UNAVAILABLE:
                    _logger.error("Unavailable video, subtitle fetch will be disabled: %s", e)
                case Flags.YOUTUBE_AGE_RESTRICTED:
                    _logger.error("Age confirmation required. Run again with cookies: %s", e)
                case str():
                    _logger.error("Unexpected video flag %r: %s", flag, e)

            if flag:
                self.flags |= {*self.flags, flag}
            else:
                raise

        else:
            if download_subtitles:
                self._fetch_youtube_subtitles__skip_missing(download_subtitles)

    def _fetch_youtube_subtitles__skip_missing(self, langs: list[str], days: int = 7) -> None:
        """
        disable subtitle fetch for videos that were published 1+week ago and are missing the subtitles
        """
        week_ago = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=days)
        is_old = self.published_at is None or self.published_at <= week_ago

        if is_old:
            stored_langs = {
                item.lang for item in self.list_content(lambda x: x.item_type == "subtitle" and x.source == "youtube")
            }
            missing_langs = {lang for lang in langs if lang not in stored_langs}

            if missing_langs:
                _logger.info(
                    "No subtitles for %s languages fetched for older video ID=%s, will be skipped next time",
                    missing_langs,
                    self.id,
                )
                self.youtube_subtitles |= {lang: "missing" for lang in missing_langs}


# Following imports must be at the end of file to prevent cyclic import error
# flake8: noqa: E402
from .channel import ChannelRecord
