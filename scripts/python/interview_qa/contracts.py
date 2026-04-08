from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CandidateJob:
    """Runtime job payload used by the prediction pipeline."""

    job_id: int
    title: str
    company: str
    location: str
    jd_text: str
    cv_text: str


@dataclass(slots=True)
class EvidenceChunk:
    """Grounding chunk selected by the lightweight ranking stage."""

    chunk_id: str
    source: str
    text: str
    score: float = 0.0
    question_id: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        """Return a compact public payload for persistence and reporting."""
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "score": round(float(self.score), 6),
            "question_id": self.question_id,
        }


@dataclass(slots=True)
class RankedQuestion:
    """Question-bank item selected by the light ranker."""

    question_id: str
    question: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize ranked question metadata for logs and outputs."""
        return {
            "id": self.question_id,
            "question": self.question,
            "score": round(float(self.score), 6),
        }
