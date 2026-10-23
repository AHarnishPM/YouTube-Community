"""Validated interfaces shared by CLI, evaluation, and the backend adapter."""
from dataclasses import dataclass, asdict
import math
from typing import Protocol


def probability(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("score/threshold must be a finite number in [0, 1]")
    return float(value)


@dataclass(frozen=True)
class Segment:
    segment_id: str
    video_id: str
    start: float
    end: float
    text: str

    def __post_init__(self):
        for key in ("segment_id", "video_id", "text"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a nonempty string")
        if len(self.text) > 12000:
            raise ValueError("segment text exceeds 12000 characters; split upstream")
        for value in (self.start, self.end):
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("timestamps must be finite numbers in seconds")
        if not 0 <= self.start < self.end:
            raise ValueError("expected 0 <= start < end")

    @classmethod
    def from_dict(cls, row):
        return cls(**{key: row[key] for key in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Score:
    positive_score: float
    reason: str

    def __post_init__(self):
        probability(self.positive_score)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be nonempty text")


class Detector(Protocol):
    name: str
    def score(self, segment: Segment) -> Score: ...


def detect(segment: Segment, detector: Detector, threshold: float = 0.5):
    threshold = probability(threshold)
    result = detector.score(segment)
    return {
        **asdict(segment),
        "is_context_worthy": result.positive_score >= threshold,
        # This always means positive-class score, not confidence in the winning class.
        "confidence": result.positive_score,
        "reason": result.reason,
        "detector": detector.name,
        "threshold": threshold,
    }
