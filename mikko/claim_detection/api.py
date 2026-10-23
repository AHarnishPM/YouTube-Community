"""Local integration adapter; Aaron can mount router in the shared FastAPI app."""
from typing import Literal
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .core import Segment, detect
from .detectors import make_detector, InferenceError


class SegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    segment_id: str = Field(min_length=1)
    video_id: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=12000)


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    segments: list[SegmentInput] = Field(min_length=1, max_length=32)
    detector: Literal["rules", "ollama"] = "rules"
    threshold: float = Field(default=0.5, ge=0, le=1)


class ClaimResult(SegmentInput):
    is_context_worthy: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    detector: str
    threshold: float


class DetectResponse(BaseModel):
    schema_version: str = "1.0"
    predictions: list[ClaimResult]


router = APIRouter()


@router.post("/v1/claims/detect", response_model=DetectResponse)
def detect_claims(body: DetectRequest):
    try:
        segments = [Segment(**s.model_dump()) for s in body.segments]
        if len({s.segment_id for s in segments}) != len(segments):
            raise ValueError("duplicate segment_id in batch")
        detector = make_detector(body.detector)
        return {"schema_version": "1.0", "predictions": [
            detect(s, detector, body.threshold) for s in segments]}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except InferenceError as exc:
        raise HTTPException(503, "Ollama unavailable or returned invalid output; retry explicitly") from exc


app = FastAPI(title="Mikko Claim Detection", version="0.1.0")
app.include_router(router)
