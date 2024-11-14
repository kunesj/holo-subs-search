#!/usr/bin/env python3.11

import os
import dataclasses
import datetime
from typing import Iterator

from yt_dlp import YoutubeDL
import srt

DOWNLOAD_PATH = "./DOWNLOADED"
VIDEO_IDS = ["TeJT-RDzi2c"]

# Download SRT files

params = {
    # download automatic subtitles and convert them to SRT format
    "skip_download": True,
    "writeautomaticsub": True,
    "writesubtitles": True,
    "subtitleslangs": ["en"],
    'postprocessors': [
        {
            'key': 'FFmpegSubtitlesConvertor',
            'format': 'srt',
            'when': 'before_dl'
        }
    ],
    # save to specific file
    "paths": {
        "subtitle": DOWNLOAD_PATH
    },
    "outtmpl": {
        "subtitle": "%(id)s.%(ext)s"  # .en.srt suffix is added automatically
    }
}


def get_srt_paths(video_ids: list[str]) -> dict[str, str]:
    paths = {
        id_: os.path.join(DOWNLOAD_PATH, f"{id_}.en.srt")
        for id_ in video_ids
    }
    
    if fetch_video_ids := {id_ for id_, path in paths.items() if not os.path.exists(path)}:
        with YoutubeDL(params=params) as ydl:
            error_code = ydl.download([f"https://www.youtube.com/watch?v={id_}" for id_ in fetch_video_ids])
            if error_code != 0:
                raise Exception("yt-dlp download failed!")
    
    if missing_paths := {path for path in paths.values() if not os.path.exists(path)}:
        raise Exception("Downloaded SRT files not found", missing_paths)
    
    return paths


# Parse SRT files


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


for video_id, srt_path in get_srt_paths(VIDEO_IDS).items():
    for line in parse_srt_file(srt_path):
        print(line.to_json())
