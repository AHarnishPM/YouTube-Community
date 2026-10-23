"""Load the hand-written upstream fixtures. See fixtures/README.md."""

from __future__ import annotations

import json
from pathlib import Path

from rag.models import ClaimDetection, TranscriptSegment

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_segments(path: Path | None = None) -> list[TranscriptSegment]:
    p = path or FIXTURE_DIR / "transcript_segments.json"
    return [TranscriptSegment(**r) for r in json.loads(p.read_text(encoding="utf-8"))]


def load_detections(path: Path | None = None) -> list[ClaimDetection]:
    p = path or FIXTURE_DIR / "claim_detections.json"
    return [ClaimDetection(**r) for r in json.loads(p.read_text(encoding="utf-8"))]


def context_worthy_claims(
    segments: list[TranscriptSegment] | None = None,
    detections: list[ClaimDetection] | None = None,
) -> list[TranscriptSegment]:
    """The segments that enter retrieval: those the detector gated through.

    This is the exact join the real pipeline performs, so building against
    fixtures exercises the same code path as Member 2's detector will.
    """
    segs = {s.segment_id: s for s in (segments or load_segments())}
    dets = detections or load_detections()
    return [
        segs[d.segment_id]
        for d in dets
        if d.is_context_worthy and d.segment_id in segs
    ]
