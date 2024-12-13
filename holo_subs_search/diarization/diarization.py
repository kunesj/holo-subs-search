from __future__ import annotations

from pydantic import BaseModel, ConfigDict

_config = ConfigDict(
    validate_assignment=True,
    validate_default=True,
    validate_return=True,
    arbitrary_types_allowed=True,
    extra="allow",
)


class DiarizationSegment(BaseModel):
    model_config = _config

    start: float
    end: float
    speaker: str


class Diarization(BaseModel):
    model_config = _config

    # configuration

    checkpoint: str  # E.g.: pyannote/speaker-diarization-3.1
    segmentation_model: str | None
    segmentation_batch_size: int
    embedding_model: str | None
    embedding_batch_size: int
    embedding_exclude_overlap: bool
    clustering: str

    # result

    segments: list[DiarizationSegment]  # VERY IMPORTANT: segments can overlap
    embeddings: dict[str, list[float]]
