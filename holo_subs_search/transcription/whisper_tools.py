from __future__ import annotations

import io
import itertools
import logging
import pathlib
from typing import TYPE_CHECKING

import openai
import openai.types.audio
import pydub

from .transcription import Transcription
from .voice_activity import VoiceActivityChunk, diarization_to_voice_activity

if TYPE_CHECKING:
    from ..diarization import Diarization

_logger = logging.getLogger(__name__)

# Audio formats that are supported by Whisper
WHISPER_AUDIO_FORMATS = ["flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm"]


def transcribe_audio(
    file: io.BytesIO | bytes | pathlib.Path,
    *,
    api_base_url: str,
    api_key: str,
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
    client = openai.OpenAI(api_key=api_key, base_url=api_base_url)
    transcript = client.audio.transcriptions.create(
        file=file,
        model=model,
        language=openai.NOT_GIVEN if lang is None else lang,
        prompt=openai.NOT_GIVEN if prompt is None else prompt,
        response_format="verbose_json",
        temperature=openai.NOT_GIVEN if temperature is None else temperature,
        timestamp_granularities=["segment"],
        timeout=openai.NOT_GIVEN if timeout is None else timeout,
    )
    return Transcription.from_openai_transcription(transcript)


def transcribe_diarized_audio(
    file: io.BytesIO | bytes | pathlib.Path,
    dia: Diarization,
    *,
    api_base_url: str,
    api_key: str,
    model: str,
    lang: str | None = None,
    prompt: str | None = None,
    temperature: float | None = None,
    timeout: str | None = None,
) -> Transcription:
    # calculate chunks

    _logger.info("Converting diarization to voice activity...")
    chunks, dia2va_params = diarization_to_voice_activity(dia)

    # prepare audio

    _logger.info("Loading audio into pydub.AudioSegment...")
    audio = pydub.AudioSegment.from_file(file)

    # transcribe chunks

    _logger.info("Transcribing %r audio chunks...", len(chunks))
    chunk_txs = []

    def _transcribe_chunk(chunk: VoiceActivityChunk, lang: str | None = None) -> Transcription:
        file_segment = io.BytesIO()
        audio[chunk.start * 1000 : chunk.end * 1000].export(file_segment, format="wav")

        tx = transcribe_audio(
            file=file_segment,
            api_base_url=api_base_url,
            api_key=api_key,
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

        return tx

    for idx, chunk in enumerate(chunks):
        _logger.info("Chunk %r/%r: %r", idx + 1, len(chunks), chunk)
        tx = _transcribe_chunk(chunk, lang=lang)
        _logger.debug("Transcription %r/%r: %r", idx + 1, len(chunks), tx)

        chunk_txs.append(tx)

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
