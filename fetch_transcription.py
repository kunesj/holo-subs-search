#!/usr/bin/env python3.11

from yt_dlp import YoutubeDL
import srt
import os

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

with YoutubeDL(params=params) as ydl:
    error_code = ydl.download([f"https://www.youtube.com/watch?v={_id}" for _id in VIDEO_IDS])
    if error_code != 0:
        raise Exception("yt-dlp download failed!")

# Parse SRT files

for video_id in VIDEO_IDS:
    file_path = os.path.join(DOWNLOAD_PATH, f"{video_id}.en.srt")
    if not os.path.exists(file_path):
        raise Exception(f"Downloaded SRT file not found: {file_path}")

    with open(file_path, "r") as f:
        srt_data = f.read()


    for sub in srt.parse(srt_data):
        print(sub)
