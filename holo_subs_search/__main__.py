#!/usr/bin/env python3.11

import argparse
import datetime
import logging
import os
import pathlib
import shutil
from typing import Callable

import termcolor

from . import diarization, holodex_tools, transcription
from .storage import ChannelRecord, FilterPart, Flags, Storage, VideoRecord
from .storage.content_item import MULTI_LANG, AudioItem, SubtitleItem

_logger = logging.getLogger(__name__)
DIR_PATH = pathlib.Path(os.path.dirname(__file__))
DEFAULT_STORAGE_PATH = (DIR_PATH / "../data/").absolute()


def _search_video_subtitles(
    storage: Storage,
    value: str,
    *,
    regex: bool = False,
    video_filter: Callable[[VideoRecord], bool] | None = None,
    subtitle_filter: Callable[[SubtitleItem], bool] | None = None,
    time_before: int = 15,
    time_after: int = 15,
) -> None:
    if not subtitle_filter:
        subtitle_filter = SubtitleItem.build_filter()

    for video in storage.list_videos(video_filter):
        for item in video.list_content(subtitle_filter):
            tx = item.load_transcription()
            searchable = transcription.SearchableTranscription.from_transcription(tx)

            header_printed = False
            for match_idx, indexes in enumerate(searchable.search(value=value, regex=regex)):
                # print header with general info about the video

                if not header_printed:
                    parts = [
                        video.published_at.strftime("%Y-%m-%d") if video.published_at else None,
                        video.id,
                        item.content_id,
                        ",".join(tx.get_main_langs()),
                    ]

                    if Flags.YOUTUBE_MEMBERSHIP in video.flags:
                        parts.append("members-only")

                    parts.append(video.title)
                    termcolor.cprint(f">>>>>>>>>> {' | '.join(parts)}", color="green", attrs=["bold"])
                    header_printed = True

                # print timestamp of the match and url to open it

                ts_segment = searchable.segments[indexes[0]]
                ts_seconds = int(ts_segment.start)
                ts_url = f"{video.youtube_url}&t={ts_seconds}"
                termcolor.cprint(f">>>>> {datetime.timedelta(seconds=ts_seconds)} | {ts_url}", attrs=["bold"])

                # expand range of printed lines to add context

                left_edge_index = searchable.index_to_past_index(indexes[0], delta_t=time_before)
                right_edge_index = searchable.index_to_future_index(indexes[-1], delta_t=time_after)

                # print match lines

                for line_idx in range(left_edge_index, right_edge_index + 1):
                    ts_segment = searchable.segments[line_idx]
                    ts_seconds = int(ts_segment.start)

                    if line_idx in indexes:
                        ts_content = termcolor.colored(ts_segment.text, "magenta")
                    else:
                        ts_content = ts_segment.text

                    print(f"{datetime.timedelta(seconds=ts_seconds)} | {ts_content}")


# flake8: noqa: C801
def main() -> None:
    # parse arguments

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--storage",
        default=DEFAULT_STORAGE_PATH,
    )
    parser.add_argument(
        "--storage-git-privacy",
        choices=["private", "public"],
        default=None,
        help="Sets storage to specified privacy level. "
        "Storage with 'public' privacy level will automatically create `.gitignore` "
        "files that will exclude membership content from git.",
    )
    parser.add_argument(
        "-d",
        "--debug",
        type=int,
        choices=[50, 40, 30, 20, 10, 1],
        default=20,
        help="Set global debug level [CRITICAL=50, ERROR=40, WARNING=30, INFO=20, DEBUG=10, SPAM=1]",
    )
    # ---- fetching metadata ----
    parser.add_argument(
        "--fetch-org-channels",
        default=None,  # "All Vtubers", "Hololive", "Nijisanji", "Independents"
    )
    parser.add_argument(
        "--refresh-channels",
        action="store_true",
    )
    parser.add_argument(
        "--refresh-videos",
        action="store_true",
    )
    parser.add_argument(
        "--update-stored",
        action="store_true",
        help="If already stored Holodex/Youtube/... info should be updated",
    )
    # ---- record filters ----
    parser.add_argument(
        "--channel-filter",
        nargs="+",
        type=str,
        default=[],
        help="`--channel-filter id:eq:***** flags:excludes:****` Can be used to limit what channels are processed. "
        "Used only when refreshing channels or video lists.",
    )
    parser.add_argument(
        "--video-filter",
        nargs="+",
        type=str,
        default=[],
        help="`--video-filter id:eq:***** flags:excludes:****` Can be used to limit what videos are processed",
    )
    # ---- YouTube ----
    parser.add_argument(
        "--youtube-memberships",
        nargs="+",
        type=str,
        default=[],
        help="`--youtube-memberships ID ID ID` Youtube IDs of channels that should also fetch membership videos",
    )
    parser.add_argument(
        "--youtube-cookies-from-browser",
        default=None,
        help="Eg. `chrome`, see yt-dlp docs for more options",
    )
    parser.add_argument(
        "--youtube-fetch-subtitles",
        action="store_true",
    )
    parser.add_argument(
        "--youtube-fetch-subtitles-langs",
        nargs="+",
        type=str,
        default=["en"],
        help="`--youtube-fetch-subtitles-langs en jp id`",
    )
    parser.add_argument(
        "--youtube-fetch-audio",
        action="store_true",
    )
    parser.add_argument(
        "--youtube-clear-audio",
        action="store_true",
        help="Delete downloaded youtube audio after it has been processed",
    )
    parser.add_argument(
        "--youtube-force",
        action="store_true",
        help="Don't skip already processed or unavailable items",
    )
    # ---- HuggingFace ----
    parser.add_argument(
        "--huggingface-token",
        default=None,
    )
    # ---- Pyannote ----
    parser.add_argument(
        "--pyannote-diarize-audio",
        action="store_true",
    )
    parser.add_argument(
        "--pyannote-api-base-url",
        default="http://localhost:8001/",
        help="Url of pyannote-server API",
    )
    parser.add_argument(
        "--pyannote-diarization-model",
        default=diarization.DIARIZATION_MODEL,
    )
    parser.add_argument(
        "--pyannote-embedding-model",
        default=diarization.EMBEDDING_MODEL,
    )
    parser.add_argument(
        "--pyannote-force",
        action="store_true",
        help="Don't skip already processed items",
    )
    # ---- Whisper ----
    parser.add_argument(
        "--whisper-transcribe-audio",
        action="store_true",
    )
    parser.add_argument(
        "--whisper-api-key",
        default="placeholder",  # can be empty/placeholder for local api
    )
    parser.add_argument(
        "--whisper-api-base-url",
        default="http://localhost:8000/v1/",
        help="Url of OpenAI-compatible API with whisper support.",
    )
    parser.add_argument(
        "--whisper-model",
        default=transcription.model_size_and_audio_lang_to_model(model_size="large", audio_lang=None),
        help=(
            "Name of specific Whisper model to load. "
            "Use HuggingFace model names with OpenAI-compatible API, or `whisper-1` with official OpenAI API."
        ),
    )
    parser.add_argument(
        "--whisper-langs",
        nargs="+",
        type=str,
        default=[MULTI_LANG],
        help=(
            f"`--whisper-langs en ja id {MULTI_LANG}`\n"
            f"- {MULTI_LANG!r} lets whisper automatically detect language of audio chunks, "
            f"the output will contain multiple languages.\n"
            "- Other values will transcribe+translate audio to specified language."
        ),
    )
    parser.add_argument(
        "--whisper-force",
        action="store_true",
        help="Don't skip already processed items",
    )
    # ---- search subtitles ----
    parser.add_argument(
        "--search",
        default=None,
    )
    parser.add_argument(
        "--search-regex",
        action="store_true",
    )
    parser.add_argument(
        "--search-subtitle-filter",
        nargs="+",
        type=str,
        default=["langs:includes:en"],
        help="`--search-subtitle-filter source:eq:youtube langs:includes:en`",
    )
    args = parser.parse_args()

    # logger configuration

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(args.debug)

    logging.getLogger("openai").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("httpcore").setLevel(logging.INFO)

    # storage

    storage_path = pathlib.Path(args.storage)
    _logger.info("Storage: %s", storage_path)
    storage = Storage(path=storage_path)

    if git_privacy := args.storage_git_privacy:
        _logger.info("Setting storage git privacy to: %s", git_privacy)
        storage.git_privacy = git_privacy
        for video in storage.list_videos():
            video.update_gitignore()

    # build filters

    channel_filter = ChannelRecord.build_str_filter(*args.channel_filter)
    video_filter = VideoRecord.build_str_filter(*args.video_filter)
    search_subtitle_filter = SubtitleItem.build_str_filter(*args.search_subtitle_filter)

    # fetch/refresh channels

    fetch_holodex_ids = set()

    if args.refresh_channels:
        for channel in storage.list_channels(channel_filter):
            if channel.holodex_id and Flags.HOLODEX_PRESERVE not in channel.flags and args.update_stored:
                fetch_holodex_ids.add(channel.holodex_id)

    if args.fetch_org_channels:
        _logger.info("Fetching %r channels...", args.fetch_org_channels)
        for value in holodex_tools.download_org_channels(org=args.fetch_org_channels):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.info("Refreshing stored channels...")
        for value in holodex_tools.download_channels(channel_ids=set(fetch_holodex_ids)):
            ChannelRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            fetch_holodex_ids -= {value.id}

    if fetch_holodex_ids:
        _logger.error("Some Holodex channels are indexed, but could not be fetched: %s", fetch_holodex_ids)

    # refreshing/fetching video info

    if args.refresh_videos:
        _logger.info("Refreshing videos...")

        holodex_channel_ids = {
            channel.holodex_id
            for channel in storage.list_channels(channel_filter)
            if channel.holodex_id and Flags.MENTIONS_ONLY not in channel.flags
        }
        for value in holodex_tools.download_channel_video_info(holodex_channel_ids):
            if value.status in ("new", "upcoming", "live"):
                continue
            video = VideoRecord.from_holodex(storage=storage, value=value, update_holodex_info=args.update_stored)
            video.update_gitignore()

    # process video
    # TODO: queue every step in separate thread to allow starting download/diarization/transcription of next video
    #  while first one is not finished

    for video in storage.list_videos(video_filter):
        # fetching YouTube content

        if args.youtube_fetch_subtitles or args.youtube_fetch_audio and video.youtube_id:
            video.fetch_youtube(
                download_subtitles=args.youtube_fetch_subtitles_langs if args.youtube_fetch_subtitles else None,
                download_audio=args.youtube_fetch_audio,
                cookies_from_browser=args.youtube_cookies_from_browser,
                memberships=args.youtube_memberships,
                force=args.youtube_force,
            )
            video.update_gitignore()

        # diarize audio with pyannote

        if args.pyannote_diarize_audio:
            video.pyannote_diarize_audio(
                api_base_url=args.pyannote_api_base_url,
                diarization_model=args.pyannote_diarization_model,
                embedding_model=args.pyannote_embedding_model,
                huggingface_token=args.huggingface_token,
                force=args.pyannote_force,
            )

        # transcribe audio with whisper

        if args.whisper_transcribe_audio:
            video.whisper_transcribe_audio(
                api_base_url=args.whisper_api_base_url,
                api_key=args.whisper_api_key,
                model=args.whisper_model,
                langs=args.whisper_langs,
                force=args.whisper_force,
            )

        # clear audio

        if args.youtube_clear_audio:
            for audio_item in video.list_content(
                AudioItem.build_filter(FilterPart(name="source", operator="eq", value="youtube"))
            ):
                _logger.info("Clearing audio item %r of video %r", audio_item.content_id, video.id)
                shutil.rmtree(audio_item.path)

    # searching parsed subtitles

    if args.search is not None:
        _logger.info("Searching subtitles...")
        _search_video_subtitles(
            storage,
            value=args.search,
            regex=args.search_regex,
            video_filter=video_filter,
            subtitle_filter=search_subtitle_filter,
        )


if __name__ == "__main__":
    main()
