from __future__ import annotations

import asyncio
import io
import pathlib
import tempfile

# noinspection PyPackageRequirements
import ffmpeg  # ffmpeg-python


async def read_chunk(file_path: pathlib.Path, start: float, end: float, format: str = "wav") -> io.BytesIO:
    with tempfile.TemporaryDirectory() as tmpdir:
        chunk_path = pathlib.Path(tmpdir) / f"chunk.{format}"

        stream = ffmpeg.input(str(file_path), ss=start, to=end, accurate_seek=None, hide_banner=None, loglevel="error")
        stream = ffmpeg.output(stream, str(chunk_path), format=format)
        await asyncio.to_thread(lambda: ffmpeg.run(stream))

        return io.BytesIO(chunk_path.read_bytes())


async def extract_audio(source_path: pathlib.Path, target_path: pathlib.Path) -> None:
    stream = ffmpeg.input(str(source_path), hide_banner=None, loglevel="error")
    stream = ffmpeg.output(stream, str(target_path), map="0:a", c="copy")
    await asyncio.to_thread(lambda: ffmpeg.run(stream))
