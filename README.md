# HoloSubs Search

Tool for searching transcriptions of vtuber videos.

Uses data from [Holodex](https://holodex.net), subtitles and audio from Youtube, and [Whisper](https://github.com/fedirz/faster-whisper-server) for directly converting YouTube audio into subtitles.

![example.png](./example.png)


## Setup

- Use Python 3.11+
- Install dependencies with `python3.11 -m pip install -r requirements.txt`
- Start with `HOLODEX_API_KEY` env variable


## Quickstart

- Fetch list of all Hololive channels

    ```bash
    python3.11 -m holo_subs_search --fetch-org-channels Hololive
    ```


- Go to `./data/channels/` and delete the channels you don't care about. This will greatly limit the amount of data that will have to be downloaded, and will speed everything up.


- Fetch list of all videos for the channels you did not delete and collabs on other channels.

    ```bash
    python3.11 -m holo_subs_search --refresh-videos
    ```


- Fetch subtitles for all videos (This takes a while). Only English subtitles are downloaded by default.

    ```bash
    python3.11 -m holo_subs_search --youtube-fetch-subtitles
    python3.11 -m holo_subs_search --youtube-fetch-subtitles --youtube-fetch-subtitles-langs en jp id
    ```


- (Optional) Fetch subtitles for membership videos. This requires you to have membership and be logged in your browser.

    ```bash
    python3.11 -m holo_subs_search --youtube-fetch-subtitles --youtube-memberships UCHsx4Hqa-1ORjQTh9TYDhww --youtube-cookies-from-browser chrome
    ```

  Membership videos automatically create `.gitignore` files that exclude fetched subtitles from git, so that the storage directory can be a git repo.


- Search

    ```bash
    python3.11 -m holo_subs_search --search "solo live"
    python3.11 -m holo_subs_search --search "solo.*?live" --search-regex
    python3.11 -m holo_subs_search --search "solo live" --search-sources youtube --search-langs en
    ```


## Audio Transcription

Some videos completely lack subtitles or the subtitles are VERY bad. In this case, you can try to download the audio and transcribe it yourself. The results can be better or worse depending on a lot of variables.


- Download all audio files

    ```bash
    python3.11 -m holo_subs_search --youtube-fetch-audio
    ```


- Start `Whisper` server

    ```bash
    docker compose --file whisper.docker-compose.yml up
    ```

    Default settings requires Docker with GPU support and a relatively powerful Nvidia GPU. 
    
    For example: Transcription of 3.5 hours long video took 2 minutes with `tiny` model on `Nvidia RTX 3090`.
    
    Alternatively, you should be able to use the Whisper from official OpenAI API with `--whisper-api-base-url`, `--whisper-api-key` and `--whisper-model-name` parameters.


- Transcribe the audio files into subtitles

    ```bash
    python3.11 -m holo_subs_search --whisper-transcribe-audio --whisper-model-size tiny
    ```


- Search transcribed audio

    ```bash
    python3.11 -m holo_subs_search --search "solo live" --search-sources whisper
    ```


## Downloaded Data

If you don't want to spend many hours/days downloading everything, then data for some channels can be found in following repos. Use `--storage PATH` to search data in downloaded repo.

- https://github.com/kunesj/holo-subs-search-data


## Development

Use `pre-commit`
