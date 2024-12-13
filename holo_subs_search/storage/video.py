from __future__ import annotations

import datetime
import json
import logging
import time
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Self

import yt_dlp
from holodex.model.channel_video import ChannelVideoInfo as HolodexChannelVideoInfo

from .. import diarization, transcription, ydl_tools
from ..utils import AwareDateTime, get_checksum, json_dumps
from .content_item import MULTI_LANG, AudioItem, DiarizationItem, SubtitleItem
from .mixins.content_mixin import ContentMixin
from .mixins.filterable_mixin import FilterPart
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
        """
        IMPORTANT:
            Holodex channel ID might not match actual channel ID of the YouTube video!
            Example: https://holodex.net/watch/sohZeczXXdY
            But it should not break anything.
        """
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

    def save_json_file(self, name: str, value: dict[str, Any] | None) -> None:
        super().save_json_file(name, value)

        if name in (self.HOLODEX_JSON, self.YOUTUBE_JSON):
            flags = {*self.flags}

            # Membership
            # - IMPORTANT: Holodex membership value might be wrong! youtube_info must have priority.

            if self.holodex_info and (topic_id := self.holodex_info.get("topic_id")):
                if topic_id == "membersonly":
                    flags |= {Flags.YOUTUBE_MEMBERSHIP}
                else:
                    flags -= {Flags.YOUTUBE_MEMBERSHIP}

            if self.youtube_info and (availability := self.youtube_info.get("availability")):
                if availability == "subscriber_only":
                    flags |= {Flags.YOUTUBE_MEMBERSHIP}
                else:
                    flags -= {Flags.YOUTUBE_MEMBERSHIP}

            # Age restriction

            if self.youtube_info:
                if self.youtube_info.get("age_limit", 0) > 0:
                    flags |= {Flags.YOUTUBE_AGE_RESTRICTED}
                elif self.youtube_info.get("availability") == "needs_auth":
                    flags |= {Flags.YOUTUBE_AGE_RESTRICTED}
                else:
                    flags -= {Flags.YOUTUBE_AGE_RESTRICTED}  # probably age restricted

            self.flags = flags

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
        is_ignored = self.storage.git_privacy == "public" and Flags.YOUTUBE_MEMBERSHIP in self.flags

        if is_ignored and not gitignore_path.exists():
            gitignore_path.write_text("/content\n")
        elif not is_ignored and gitignore_path.exists():
            gitignore_path.unlink()

    # Youtube

    def fetch_youtube(
        self,
        *,
        download_subtitles: list[str] | None = None,
        download_audio: bool = False,
        cookies_from_browser: str | None = None,
        memberships: list[str] | None = None,
        force: bool = False,
    ) -> None:
        _logger.debug("Fetching Youtube subtitles/audio for video %s - %s", self.id, self.published_at)

        # check if video can be accessed

        if not force:
            if Flags.YOUTUBE_PRIVATE in self.flags:
                return
            elif Flags.YOUTUBE_UNAVAILABLE in self.flags:
                return
            elif Flags.YOUTUBE_AGE_RESTRICTED in self.flags and not cookies_from_browser:
                return

            if Flags.YOUTUBE_MEMBERSHIP in self.flags:
                channel = self.storage.get_channel(self.channel_id)
                if not channel.exists() or channel.youtube_id not in (memberships or []):
                    return  # not accessible membership video

        # calculate what subtitles to download

        if download_subtitles and not force:
            fetch_langs = set(download_subtitles) - set(self.youtube_subtitles.keys())
            for item in self.list_content(
                lambda x: x.item_type == "subtitle" and x.source == "youtube" and x.lang in fetch_langs
            ):
                fetch_langs -= {item.lang}
            download_subtitles = list(fetch_langs)

        # calculate if audio should be downloaded

        if download_audio and not force:
            download_audio = not bool(
                list(
                    self.list_content(AudioItem.build_filter(FilterPart(name="source", operator="eq", value="youtube")))
                )
            )

        # fetch content

        if not download_subtitles and not download_audio:
            return

        _logger.info(
            "Fetching Youtube subtitles/audio: video_id=%r, published_at=%r, download_subtitles=%r, download_audio=%r",
            self.id,
            self.published_at,
            download_subtitles,
            download_audio,
        )
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
                            for key in ["formats", "automatic_captions", "subtitles", "thumbnails", "heatmap"]:
                                info.pop(key, None)

                            self.youtube_info = info

                elif any(name.endswith(f".{x}") for x in transcription.WHISPER_AUDIO_FORMATS):
                    with open(file_path, "rb") as f:
                        content = f.read()
                        content_id = AudioItem.build_content_id("youtube", get_checksum(content), name)
                        item = AudioItem(path=self.content_path / content_id)

                        metadata = AudioItem.build_metadata(source="youtube", audio_file=name)
                        item.create(metadata)
                        item.audio_path.write_bytes(content)

                elif name.endswith(".srt"):  # youtube.en.srt
                    with open(file_path, "rb") as f:
                        content = f.read()
                        content_id = SubtitleItem.build_content_id("youtube", get_checksum(content), name)
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
                            langs={lang},
                            flags=flags,
                            subtitle_file=name,
                        )
                        item.create(metadata)
                        item.subtitle_path.write_bytes(content)

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
                item.lang
                for item in self.list_content(
                    SubtitleItem.build_filter(FilterPart(name="source", operator="eq", value="youtube"))
                )
            }
            missing_langs = {lang for lang in langs if lang not in stored_langs}

            if missing_langs:
                _logger.info(
                    "No subtitles for %s languages fetched for older video ID=%s, will be skipped next time",
                    missing_langs,
                    self.id,
                )
                self.youtube_subtitles = dict(self.youtube_subtitles) | {lang: "missing" for lang in missing_langs}

    # Pyannote

    def pyannote_diarize_audio(
        self,
        *,
        api_base_url: str,
        checkpoint: str,
        huggingface_token: str | None = None,
        force: bool = False,
    ) -> None:
        _logger.debug("Diarizing audio for video %s - %s", self.id, self.published_at)

        for audio_item in self.list_content(AudioItem.build_filter()):
            # check for existing results

            dia_items = list(
                self.list_content(
                    DiarizationItem.build_filter(
                        FilterPart(name="source", operator="eq", value="pyannote"),
                        FilterPart(name="audio_id", operator="eq", value=audio_item.content_id),
                        FilterPart(name="checkpoint", operator="eq", value=checkpoint),
                    )
                )
            )

            if dia_items and not force:
                continue

            for dia_item in dia_items:
                dia_item.path.unlink()

            # diarize audio

            _logger.info(
                "Starting diarization: video_id=%r, audio_id=%r, checkpoint=%s",
                self.id,
                audio_item.content_id,
                checkpoint,
            )

            start_time = time.time()
            dia = diarization.audio_to_diarization_response(
                path=audio_item.audio_path,
                api_base_url=api_base_url,
                checkpoint=checkpoint,
                huggingface_token=huggingface_token,
            )
            end_time = time.time()

            _logger.info("Diarization finished in %i seconds", end_time - start_time)

            # save diarization file

            checksum = get_checksum(json.dumps(dia.model_dump(mode="json"), sort_keys=True).encode("utf-8"))
            content_id = DiarizationItem.build_content_id("pyannote", checksum)
            item = DiarizationItem(path=self.content_path / content_id)

            metadata = DiarizationItem.build_metadata(
                source="pyannote",
                audio_id=audio_item.content_id,
            )
            item.create(metadata)
            item.save_diarization(dia)

    # Whisper

    def whisper_transcribe_audio(
        self,
        *,
        api_base_url: str,
        api_key: str,
        model: str,
        langs: set[str],  # can have special MULTI_LANG value
        force: bool = False,
    ) -> None:
        _logger.debug("Transcribing audio for video %s - %s", self.id, self.published_at)

        for audio_item in self.list_content(AudioItem.build_filter()):
            for diarization_item in self.list_content(
                DiarizationItem.build_filter(
                    FilterPart(name="audio_id", operator="eq", value=audio_item.content_id),
                )
            ):
                for lang in langs:
                    self._whisper_transcribe_audio_to_lang(
                        api_base_url=api_base_url,
                        api_key=api_key,
                        model=model,
                        lang=lang,
                        audio_item=audio_item,
                        diarization_item=diarization_item,
                        force=force,
                    )

    def _whisper_transcribe_audio_to_lang(
        self,
        *,
        api_base_url: str,
        api_key: str,
        model: str,
        lang: str,  # can have special MULTI_LANG value
        audio_item: AudioItem,
        diarization_item: DiarizationItem,
        force: bool = False,
    ) -> None:
        """
        Note: Setting `lang` will switch whisper to translation mode.
        """
        # check for existing results

        filter_parts = [
            FilterPart(name="source", operator="eq", value="whisper"),
            FilterPart(name="audio_id", operator="eq", value=audio_item.content_id),
            FilterPart(name="diarization_id", operator="eq", value=diarization_item.content_id),
            FilterPart(name="whisper_model", operator="eq", value=model),
            FilterPart(name="lang", operator="eq", value=lang),
        ]

        sub_items = list(self.list_content(SubtitleItem.build_filter(*filter_parts)))
        if sub_items and not force:
            return

        for sub_item in sub_items:
            sub_item.path.unlink()

        # transcribe the audio into SRT format

        _logger.info(
            "Starting transcription: video_id=%r, audio_id=%r, diarization_id=%s, whisper_model=%r, lang=%r",
            self.id,
            audio_item.content_id,
            diarization_item.content_id,
            model,
            lang,
        )
        start_time = time.time()

        tx = transcription.transcribe_diarized_audio(
            file=audio_item.audio_path,
            dia=diarization_item.load_diarization(),
            api_base_url=api_base_url,
            api_key=api_key,
            model=model,
            lang=None if lang == MULTI_LANG else lang,
        )
        content = tx.model_dump_json()

        end_time = time.time()
        _logger.info("Transcription finished in %i seconds: %s", end_time - start_time, tx.get_lang_counts())

        # save subtitle file
        # - keeps transcriptions from different models and for different languages

        checksum = get_checksum(
            str(
                [
                    audio_item.content_id,
                    diarization_item.content_id,
                    model,
                    content,
                ]
            ).encode("utf-8")
        )

        name = f"transcription.{lang}.json"
        content_id = SubtitleItem.build_content_id("whisper", checksum, name)
        item = SubtitleItem(path=self.content_path / content_id)

        flags = {Flags.SUBTITLE_TRANSCRIPTION}
        if lang != MULTI_LANG:
            flags.add(Flags.SUBTITLE_TRANSLATION)

        metadata = SubtitleItem.build_metadata(
            source="whisper",
            lang=lang,
            langs=tx.get_main_langs(),
            flags=flags,
            subtitle_file=name,
            audio_id=audio_item.content_id,
            diarization_id=diarization_item.content_id,
            whisper_model=model,
        )

        item.create(metadata)
        item.subtitle_path.write_text(content)


# Following imports must be at the end of file to prevent cyclic import error
# flake8: noqa: E402
from .channel import ChannelRecord
