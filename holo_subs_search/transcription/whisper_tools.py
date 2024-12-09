from __future__ import annotations

import functools
import io
import itertools
import logging
import pathlib
from typing import TYPE_CHECKING

import openai
import openai.types.audio
import pydub
from pydantic import BaseModel, ConfigDict, computed_field

from .transcription import Transcription

if TYPE_CHECKING:
    from ..diarization import Diarization

_logger = logging.getLogger(__name__)

# Audio formats that are supported by Whisper
WHISPER_AUDIO_FORMATS = ["flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm"]


class AudioChunk(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True,
        validate_default=True,
        validate_return=True,
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    start: float
    end: float
    speakers: frozenset[str]

    @computed_field
    @functools.cached_property
    def duration(self) -> float:
        return self.end - self.start


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
    diarization: Diarization,
    *,
    api_base_url: str,
    api_key: str,
    model: str,
    prompt: str | None = None,
    temperature: float | None = None,
    timeout: str | None = None,
) -> Transcription:
    # prepare audio

    _logger.info("Loading audio into pydub.AudioSegment...")
    audio = pydub.AudioSegment.from_file(file)

    # calculate chunks

    _logger.info("Calculating audio chunks...")
    chunks = diarization_to_audio_chunks(diarization)

    # transcribe chunks

    _logger.info("Transcribing %s audio chunks...", len(chunks))
    chunk_txs = []

    def _transcribe_chunk(chunk: AudioChunk, lang: str | None = None) -> Transcription:
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
            tx_segment.end += chunk.end

        return tx

    for idx, chunk in enumerate(chunks):
        if idx % 100 == 0:
            _logger.info("Progress: %s/%s", idx + 1, len(chunks))

        _logger.debug("Chunk: %s", chunk)
        chunk_txs.append(_transcribe_chunk(chunk))

    _logger.info("Progress: DONE")

    # compute language

    langs = [tx.lang for tx in chunk_txs]
    lang = max({*langs}, key=lambda x: langs.count(x)) if langs else "en"
    _logger.info("Detected majority language: %s (%s/%s)", lang, langs.count(lang), len(langs))

    return Transcription(lang=lang, segments=list(itertools.chain.from_iterable([tx.segments for tx in chunk_txs])))


def diarization_to_audio_chunks(
    diarization: Diarization,
    *,
    padding: float = 0.5,
    min_duration: float = 0.1,
    max_duration: float = 30.0,
    max_gap: float = 2.0,
) -> list[AudioChunk]:
    # FIXME
    return [AudioChunk(start=x.start, end=x.end, speakers={x.speaker}) for x in diarization.diarization]
