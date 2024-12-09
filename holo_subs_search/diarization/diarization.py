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

    diarization_model: str
    diarization: list[DiarizationSegment]
    embedding_model: str
    embeddings: dict[str, list[float]]
