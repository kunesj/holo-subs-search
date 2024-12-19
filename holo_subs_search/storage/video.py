from __future__ import annotations

import asyncio
import datetime
import json
import logging
import pathlib
import shutil
import tempfile
import time
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self

import yt_dlp
from holodex.model.channel_video import ChannelVideoInfo as HolodexChannelVideoInfo

from .. import diarization, ffmpeg_tools, ragtag_tools, rubyruby_tools, transcription, ydl_tools
from ..env_config import (
    VIDEO_FETCH_RAGTAG_PARALLEL_COUNT,
    VIDEO_FETCH_RUBYRUBY_PARALLEL_COUNT,
    VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT,
    VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT,
    VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT,
)
from ..logging_config import logging_with_values
from ..utils import AwareDateTime, json_dumps, with_semaphore
from .content_item import MULTI_LANG, AudioItem, DiarizationItem, SubtitleItem
from .mixins.content_mixin import ContentMixin
from .mixins.filterable_mixin import FilterPart
from .mixins.flags_mixin import Flags, FlagsMixin
from .mixins.holodex_mixin import HolodexMixin
from .mixins.ragtag_mixin import RagtagMixin
from .mixins.rubyruby_mixin import RubyRubyMixin
from .record import Record

if TYPE_CHECKING:
    from .storage import Storage

SubtitlesState = Literal["missing", "garbage"]

_logger = logging.getLogger(__name__)


class VideoRecord(ContentMixin, RagtagMixin, RubyRubyMixin, HolodexMixin, FlagsMixin, Record):
    RAGTAG_JSON: ClassVar[str] = "ragtag.json"
    model_name = "video"

    # ==================================== Fields ====================================
    # region

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

    # endregion
    # ==================================== Computed properties ====================================
    # region

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

    # endregion
    # ==================================== Methods ====================================
    # region

    def save_json_file(self, name: str, value: dict[str, Any] | None) -> None:
        super().save_json_file(name, value)

        # trim down the info.json to only useful data
        if name == self.YOUTUBE_JSON:
            for key in ["formats", "automatic_captions", "subtitles", "thumbnails", "heatmap"]:
                value.pop(key, None)

        # update flags from metadata
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

    # endregion
    # ==================================== Youtube ====================================
    # region

    async def fetch_youtube(
        self,
        *,
        download_subtitles: list[str] | None = None,
        download_audio: bool = False,
        cookies_from_browser: str | None = None,
        memberships: list[str] | None = None,
        force: bool = False,
    ) -> None:
        _logger.debug("Fetching Youtube subtitles/audio for video %s - %s", self.id, self.published_at)

        async with asyncio.TaskGroup() as tg:
            coro = self._fetch_youtube_single(
                download_subtitles=download_subtitles,
                download_audio=download_audio,
                cookies_from_browser=cookies_from_browser,
                memberships=memberships,
                force=force,
            )
            tg.create_task(coro)

    @with_semaphore(VIDEO_FETCH_YOUTUBE_PARALLEL_COUNT)
    @logging_with_values(get_context=lambda self, *args, **kwargs: [f"video={self.id}", "fetch-youtube"])
    async def _fetch_youtube_single(
        self,
        *,
        download_subtitles: list[str] | None = None,
        download_audio: bool = False,
        cookies_from_browser: str | None = None,
        memberships: list[str] | None = None,
        force: bool = False,
    ) -> None:
        # check if video can be accessed

        if not self.youtube_id:
            return

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
        # - we don't care about the source. if any audio is downloaded, skip this.

        if download_audio and not force:
            download_audio = not bool(list(self.list_content(AudioItem.build_filter())))

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
            async for name, file_path in ydl_tools.download_video(
                video_id=self.youtube_id,
                download_subtitles=download_subtitles,
                download_audio=download_audio,
                cookies_from_browser=cookies_from_browser,
            ):
                if name == "info.json":
                    if not self.youtube_info or Flags.YOUTUBE_PRESERVE not in self.flags:
                        with open(file_path, "r") as f:
                            self.youtube_info = json.loads(f.read())

                elif any(name.endswith(f".{x}") for x in transcription.WHISPER_AUDIO_FORMATS):
                    with open(file_path, "rb") as f:
                        content = f.read()
                        metadata = AudioItem.build_metadata(source="youtube", audio_file=name)

                        checksum = AudioItem.build_checksum(metadata, content)
                        content_id = AudioItem.build_content_id("youtube", checksum, name)
                        item = AudioItem(path=self.content_path / content_id)

                        item.create(metadata)
                        item.audio_path.write_bytes(content)

                elif name.endswith(".srt"):  # youtube.en.srt
                    with open(file_path, "rb") as f:
                        content = f.read()
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

                        checksum = SubtitleItem.build_checksum(metadata, content)
                        content_id = SubtitleItem.build_content_id("youtube", checksum, name)
                        item = SubtitleItem(path=self.content_path / content_id)

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

    # endregion
    # ==================================== archive.ragtag.moe ====================================
    # region

    async def fetch_ragtag(self, *, download_audio: bool = False, force: bool = False) -> None:
        _logger.debug("Fetching Ragtag audio for video %s - %s", self.id, self.published_at)

        async with asyncio.TaskGroup() as tg:
            coro = self._fetch_ragtag_single(
                download_audio=download_audio,
                force=force,
            )
            tg.create_task(coro)

    @with_semaphore(VIDEO_FETCH_RAGTAG_PARALLEL_COUNT)
    @logging_with_values(get_context=lambda self, *args, **kwargs: [f"video={self.id}", "fetch-ragtag"])
    async def _fetch_ragtag_single(self, *, download_audio: bool = False, force: bool = False) -> None:
        # check if video can be processed

        if not self.youtube_id:
            return

        if not (self.flags & {Flags.YOUTUBE_PRIVATE, Flags.YOUTUBE_UNAVAILABLE}):
            # video available on YouTube, don't put any unnecessary traffic on archive
            return

        if Flags.RAGTAG_UNAVAILABLE in self.flags and not force:
            return

        # calculate if audio should be downloaded
        # - we don't care about the source. if any audio is downloaded, skip this.

        if download_audio and not force:
            download_audio = not bool(list(self.list_content(AudioItem.build_filter())))

        # fetch content

        if not download_audio:
            return

        _logger.info(
            "Fetching Ragtag video: video_id=%r, published_at=%r, download_audio=%r",
            self.id,
            self.published_at,
            download_audio,
        )

        try:
            async for ragtag_file in ragtag_tools.download_video(
                video_id=self.youtube_id, download_audio=download_audio
            ):
                match ragtag_file.file_type:
                    case "ragtag":
                        self.ragtag_info = json.loads(ragtag_file.path.read_text())

                    case "info":
                        if self.youtube_info:
                            _logger.info("Keeping original YT info.json: %s", self.id)
                        else:
                            self.youtube_info = json.loads(ragtag_file.path.read_text())

                    case "audio-only" | "video":
                        with tempfile.TemporaryDirectory() as tmpdir:
                            if ragtag_file.file_type == "video":
                                audio_name = ".".join(["audio-only", *ragtag_file.file_name.split(".")[:-1], "webm"])
                                audio_path = pathlib.Path(tmpdir) / audio_name
                                await ffmpeg_tools.extract_audio(ragtag_file.path, audio_path)
                            else:
                                audio_name = ragtag_file.file_name
                                audio_path = ragtag_file.path

                            content = audio_path.read_bytes()
                            metadata = AudioItem.build_metadata(source="ragtag", audio_file=audio_name)

                            checksum = AudioItem.build_checksum(metadata, content)
                            content_id = AudioItem.build_content_id("ragtag", checksum, audio_name)
                            item = AudioItem(path=self.content_path / content_id)

                            item.create(metadata)
                            item.audio_path.write_bytes(content)

                    case _:
                        _logger.warning("Fetched unexpected file: %s", ragtag_file)

        except ragtag_tools.RagtagNotFound as e:
            _logger.info("Video not available in archive.ragtag.moe: %s", self.id)
            self.flags |= {*self.flags, Flags.RAGTAG_UNAVAILABLE}

    # endregion
    # ==================================== streams.rubyruby.net ====================================
    # region

    async def fetch_rubyruby(self, *, download_audio: bool = False, force: bool = False) -> None:
        _logger.debug("Fetching RubyRuby audio for video %s - %s", self.id, self.published_at)

        async with asyncio.TaskGroup() as tg:
            coro = self._fetch_rubyruby_single(
                download_audio=download_audio,
                force=force,
            )
            tg.create_task(coro)

    @with_semaphore(VIDEO_FETCH_RUBYRUBY_PARALLEL_COUNT)
    @logging_with_values(get_context=lambda self, *args, **kwargs: [f"video={self.id}", "fetch-rubyruby"])
    async def _fetch_rubyruby_single(self, *, download_audio: bool = False, force: bool = False) -> None:
        # check if video can be processed

        if not self.youtube_id:
            return

        if not (self.flags & {Flags.YOUTUBE_PRIVATE, Flags.YOUTUBE_UNAVAILABLE}):
            # video available on YouTube, don't put any unnecessary traffic on archive
            return

        if Flags.RUBYRUBY_UNAVAILABLE in self.flags and not force:
            return

        # calculate if audio should be downloaded
        # - we don't care about the source. if any audio is downloaded, skip this.

        if download_audio and not force:
            download_audio = not bool(list(self.list_content(AudioItem.build_filter())))

        # fetch content

        if not download_audio:
            return

        _logger.info(
            "Fetching RubyRuby video: video_id=%r, published_at=%r, download_audio=%r",
            self.id,
            self.published_at,
            download_audio,
        )

        try:
            async for rubyruby_file in rubyruby_tools.download_video(
                video_id=self.youtube_id, members=Flags.YOUTUBE_MEMBERSHIP in self.flags, download_audio=download_audio
            ):
                match rubyruby_file.file_type:
                    case "rubyruby":
                        self.rubyruby_info = json.loads(rubyruby_file.path.read_text())

                    case "info":
                        if self.youtube_info:
                            _logger.info("Keeping original YT info.json: %s", self.id)
                        else:
                            self.youtube_info = json.loads(rubyruby_file.path.read_text())

                    case "audio-only" | "video":
                        with tempfile.TemporaryDirectory() as tmpdir:
                            if rubyruby_file.file_name.count(".") >= 2:
                                base_name = rubyruby_file.file_name.split(".", maxsplit=1)[-1]
                                base_name = f"{self.youtube_id}.{base_name}"
                            else:
                                base_name = rubyruby_file.file_name

                            if rubyruby_file.file_type == "video":
                                audio_name = ".".join(["audio-only", *base_name.split(".")[:-1], "webm"])
                                audio_path = pathlib.Path(tmpdir) / audio_name
                                await ffmpeg_tools.extract_audio(rubyruby_file.path, audio_path)
                            else:
                                audio_name = base_name
                                audio_path = rubyruby_file.path

                            content = audio_path.read_bytes()
                            metadata = AudioItem.build_metadata(source="rubyruby", audio_file=audio_name)

                            checksum = AudioItem.build_checksum(metadata, content)
                            content_id = AudioItem.build_content_id("rubyruby", checksum, audio_name)
                            item = AudioItem(path=self.content_path / content_id)

                            item.create(metadata)
                            item.audio_path.write_bytes(content)

                    case _:
                        _logger.warning("Fetched unexpected file: %s", rubyruby_file)

        except rubyruby_tools.RubyRubyNotFound as e:
            _logger.info("Video not available in streams.rubyruby.net: %s", self.id)
            self.flags |= {*self.flags, Flags.RUBYRUBY_UNAVAILABLE}

    # endregion
    # ==================================== Pyannote ====================================
    # region

    async def pyannote_diarize_audio(
        self,
        *,
        checkpoint: str,
        force: bool = False,
    ) -> None:
        _logger.debug("Diarizing audio for video %s - %s", self.id, self.published_at)

        async with asyncio.TaskGroup() as tg:
            for audio_item in self.list_content(AudioItem.build_filter()):
                coro = self._pyannote_diarize_audio_single(
                    checkpoint=checkpoint,
                    audio_item=audio_item,
                    force=force,
                )
                tg.create_task(coro)

    @with_semaphore(VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT)
    @logging_with_values(
        get_context=lambda self, checkpoint, audio_item, *args, **kwargs: [
            f"video={self.id}",
            "diarize-audio",
            # f"dia-checkpoint={checkpoint}",
            # f"dia-audio={audio_item.content_id}",
        ]
    )
    async def _pyannote_diarize_audio_single(
        self,
        *,
        checkpoint: str,
        audio_item: AudioItem,
        force: bool = False,
    ) -> None:
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
            return

        for dia_item in dia_items:
            shutil.rmtree(dia_item.path)

        # diarize audio

        _logger.info(
            "Starting diarization: video_id=%r, audio_id=%r, checkpoint=%s",
            self.id,
            audio_item.content_id,
            checkpoint,
        )

        start_time = time.time()
        dia = await diarization.audio_to_diarization_response(
            path=audio_item.audio_path,
            checkpoint=checkpoint,
        )
        end_time = time.time()

        _logger.info("Diarization finished in %i seconds", end_time - start_time)

        # save diarization file

        metadata = DiarizationItem.build_metadata(
            source="pyannote",
            audio_id=audio_item.content_id,
        )

        checksum = DiarizationItem.build_checksum(metadata, dia)
        content_id = DiarizationItem.build_content_id("pyannote", checksum)
        item = DiarizationItem(path=self.content_path / content_id)

        item.create(metadata)
        item.save_diarization(dia)

    # endregion
    # ==================================== Whisper ====================================
    # region

    async def whisper_transcribe_audio(
        self,
        *,
        model: str,
        langs: set[str],  # can have special MULTI_LANG value
        force: bool = False,
    ) -> None:
        _logger.debug("Transcribing audio for video %s - %s", self.id, self.published_at)

        async with asyncio.TaskGroup() as tg:
            for audio_item in self.list_content(AudioItem.build_filter()):
                for diarization_item in self.list_content(
                    DiarizationItem.build_filter(
                        FilterPart(name="audio_id", operator="eq", value=audio_item.content_id),
                    )
                ):
                    for lang in langs:
                        coro = self._whisper_transcribe_audio_single(
                            model=model,
                            lang=lang,
                            audio_item=audio_item,
                            diarization_item=diarization_item,
                            force=force,
                        )
                        tg.create_task(coro)

    @with_semaphore(VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT)
    @logging_with_values(
        get_context=lambda self, model, lang, audio_item, diarization_item, *args, **kwargs: [
            f"video={self.id}",
            "transcribe-audio",
            # f"tx-model={model}",
            f"tx-lang={lang}",
            # f"tx-audio={audio_item.content_id}",
            # f"tx-dia={diarization_item.content_id}",
        ]
    )
    async def _whisper_transcribe_audio_single(
        self,
        *,
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
            shutil.rmtree(sub_item.path)

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

        tx = await transcription.transcribe_diarized_audio(
            file=audio_item.audio_path,
            dia=diarization_item.load_diarization(),
            model=model,
            lang=None if lang == MULTI_LANG else lang,
        )
        content = tx.model_dump_json()

        end_time = time.time()
        _logger.info("Transcription finished in %i seconds: %s", end_time - start_time, tx.get_lang_counts())

        # save subtitle file
        # - keeps transcriptions from different models and for different languages

        flags = {Flags.SUBTITLE_TRANSCRIPTION}
        if lang != MULTI_LANG:
            flags.add(Flags.SUBTITLE_TRANSLATION)

        name = f"transcription.{lang}.json"
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

        checksum = DiarizationItem.build_checksum(metadata, content)
        content_id = SubtitleItem.build_content_id("whisper", checksum, name)
        item = SubtitleItem(path=self.content_path / content_id)

        item.create(metadata)
        item.subtitle_path.write_text(content)

    # endregion


# Following imports must be at the end of file to prevent cyclic import error
# flake8: noqa: E402
from .channel import ChannelRecord
