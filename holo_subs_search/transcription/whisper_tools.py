from __future__ import annotations

import asyncio
import io
import itertools
import logging
import pathlib
from typing import TYPE_CHECKING

import openai
import openai.types.audio
import pydub

from ..env_config import (
    VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT,
    WHISPER_API_KEY,
    WHISPER_BASE_URL,
    WHISPER_PARALLEL_COUNT,
)
from ..utils import with_semaphore
from .transcription import Transcription
from .voice_activity import VoiceActivityChunk, diarization_to_voice_activity

if TYPE_CHECKING:
    from ..diarization import Diarization

_logger = logging.getLogger(__name__)
WHISPER_API_SEMAPHORE = asyncio.Semaphore(WHISPER_PARALLEL_COUNT)
# Same parallel count as `WHISPER_API_SEMAPHORE`, to not start new chunks when api might be busy
WHISPER_CHUNK_SEMAPHORE = asyncio.Semaphore(WHISPER_PARALLEL_COUNT)
# Usually, it does not make sense for this to be more than 1, because one diarized transcription can generate many
# concurrent api calls. So we default it to number of videos we want to transcribe concurrently. That should also be 1.
WHISPER_DIARIZED_SEMAPHORE = asyncio.Semaphore(VIDEO_WHISPER_TRANSCRIBE_PARALLEL_COUNT)

# Audio formats that are supported by Whisper
WHISPER_AUDIO_FORMATS = ["flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm"]

# TODO: maybe check whisperX for VA or improvements. But don't use it by itself.
#   - https://github.com/m-bain/whisperX/blob/main/whisperx/vad.py


@with_semaphore(WHISPER_API_SEMAPHORE)
async def transcribe_audio(
    file: io.BytesIO | bytes | pathlib.Path,
    *,
    model: str,
    # It is recommended to set this as it will improve the performance.
    # See https://github.com/fedirz/faster-whisper-server/blob/master/src/faster_whisper_server/config.py#L41C7-L41C15
    # for supported values.
    lang: str | None = None,
    prompt: str | None = None,
    temperature: float | None = None,
    timeout: str | None = None,
) -> Transcription:
    """
    IMPORTANT:
    - Whisper hallucinates a lot in silent parts, so use diarization to transcribe only parts of audio with speech.
    - Whisper internally splits audio into 30s segments, which can cause transcription mistakes.

    NOTES:
    - Transcription Software Comparisons:
        https://blog.lopp.net/open-source-transcription-software-comparisons/
        - Whisper models have the best accuracy
        - Small whisper models tend to skip filler words
        https://www.gladia.io/blog/best-open-source-speech-to-text-models
        - Whisper internally splits audio into 30s chunks
    - See WHISPER_INPUT_FORMATS for supported formats
    - Whisper internally resamples audio to 16kHz, so the input does not have to be high quality
        https://dev.to/mxro/optimise-openai-whisper-api-audio-format-sampling-rate-and-quality-29fj
        https://github.com/openai/whisper/discussions/870#discussioncomment-4743438
    - I was unable to find if low bitrate has any negative effects
    """
    async with openai.AsyncOpenAI(api_key=WHISPER_API_KEY, base_url=WHISPER_BASE_URL) as client:
        transcript = await client.audio.transcriptions.create(
            file=file,
            model=model,
            language=openai.NOT_GIVEN if lang is None else lang,
            prompt=openai.NOT_GIVEN if prompt is None else prompt,
            response_format="verbose_json",
            temperature=openai.NOT_GIVEN if temperature is None else temperature,
            timestamp_granularities=["segment"],
            timeout=openai.NOT_GIVEN if timeout is None else timeout,
        )
        return Transcription.from_openai(transcript)


@with_semaphore(WHISPER_DIARIZED_SEMAPHORE)
async def transcribe_diarized_audio(
    file: io.BytesIO | bytes | pathlib.Path,
    dia: Diarization,
    *,
    model: str,
    lang: str | None = None,
    prompt: str | None = None,
    temperature: float | None = None,
    timeout: str | None = None,
) -> Transcription:
    # calculate chunks

    _logger.info("Converting diarization to voice activity...")
    chunks, dia2va_params = await asyncio.to_thread(diarization_to_voice_activity, dia)

    # prepare audio

    _logger.info("Loading audio into pydub.AudioSegment...")
    audio = await asyncio.to_thread(lambda: pydub.AudioSegment.from_file(file))

    # transcribe chunks

    _logger.info("Transcribing %r audio chunks...", len(chunks))

    @with_semaphore(WHISPER_CHUNK_SEMAPHORE)
    async def _transcribe_chunk(chunks: list[VoiceActivityChunk], idx: int, lang: str | None = None) -> Transcription:
        chunk = chunks[idx]
        _logger.info("Chunk %r/%r: %r", idx + 1, len(chunks), chunk)

        file_segment = io.BytesIO()
        audio[chunk.start * 1000 : chunk.end * 1000].export(file_segment, format="wav")

        tx = await transcribe_audio(
            file=file_segment,
            model=model,
            lang=lang,
            prompt=prompt,
            temperature=temperature,
            timeout=timeout,
        )

        # make start/end absolute
        for tx_segment in tx.segments:
            tx_segment.start += chunk.start
            tx_segment.end += chunk.start

        _logger.debug("Transcription %r/%r: %r", idx + 1, len(chunks), tx)
        return tx

    tasks = []
    async with asyncio.TaskGroup() as tg:
        for idx in range(len(chunks)):
            coro = _transcribe_chunk(chunks, idx, lang=lang)
            tasks.append(tg.create_task(coro))
    chunk_txs = [task.result() for task in tasks]

    _logger.info("Progress: DONE")

    # build transcription object and return

    segments = list(itertools.chain.from_iterable([tx.segments for tx in chunk_txs]))
    params = {
        "dia2va": dia2va_params,
        "model": model,
        "lang": lang,
        "prompt": prompt,
        "temperature": temperature,
    }
    return Transcription(segments=segments, params={k: v for k, v in params.items() if v is not None})
