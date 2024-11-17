# HoloSubs Search

Tool for searching transcriptions of vtuber videos.

Uses data from [Holodex](https://holodex.net) and (automatic) subtitles from Youtube.


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
    python3.11 -m holo_subs_search --fetch-subtitles
    python3.11 -m holo_subs_search --fetch-subtitles --fetch-subtitles-langs en jp id
    ```

- (Optional) Fetch subtitles for membership videos. This requires you to have membership and be logged in your browser.

    ```bash
    python3.11 -m holo_subs_search --fetch-subtitles --yt-members UCHsx4Hqa-1ORjQTh9TYDhww --yt-cookies-from-browser chrome
    ```

   Membership videos automatically create `.gitignore` files that exclude fetched subtitles from git, so that the storage directory can be a git repo.

- Search

    ```bash
    python3.11 -m holo_subs_search --search "solo live"
    python3.11 -m holo_subs_search --search "solo.*?live" --search-regex
    python3.11 -m holo_subs_search --search "solo live" --search-sources youtube --search-langs en
    ```


## Downloaded Data

If you don't want to spend many hours/days downloading everything, then data for some channels can be found in following repos. Use `--storage PATH` to search data in downloaded repo.

- https://github.com/kunesj/holo-subs-search-data 


## Development

Use `pre-commit`
