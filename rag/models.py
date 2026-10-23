"""Typed interface contracts for the Community Notes pipeline.

The four shared objects below are the team's agreed boundaries, fixed in the
project proposal ("Shared interfaces to lock down in week 1"). They are defined
here so the boundary is executable rather than prose: Member 3's code can be
built and measured against hand-written fixtures before Members 1 and 2 land
their sides.

    TranscriptSegment   Member 1 -> Postgres
    ClaimDetection      Member 2 -> Member 3
    Note                Member 3 -> API -> extension
    Chapter             Member 2 -> API -> extension

Do not change a shared field without renegotiating with the team.

The remaining types (EvidencePassage, Source, RetrievalResult) are internal to
the retrieval component and may change freely.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Shared contracts
# --------------------------------------------------------------------------


class TranscriptSegment(BaseModel):
    """One timestamped chunk of a video transcript. Produced by Member 1."""

    segment_id: str
    video_id: str
    start: float = Field(description="Seconds from video start.")
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClaimDetection(BaseModel):
    """Member 2's verdict on whether a segment deserves a note.

    `is_context_worthy` is the gate: only segments marked True enter the
    retrieval pipeline.
    """

    segment_id: str
    is_context_worthy: bool
    confidence: float = Field(ge=0.0, le=1.0)


class Source(BaseModel):
    """A citation in a generated note.

    `revision_id` is what makes a citation reproducible: Wikipedia article text
    changes, so pointing at a title alone does not pin the evidence we actually
    retrieved (see DESIGN-LOG D-04).
    """

    title: str
    url: str
    revision_id: int | None = None
    section: str | None = None


class Note(BaseModel):
    """The deliverable of this component: a moment-anchored, source-cited note.

    Constraint carried from the proposal: the note summarises evidence and
    cites it. It must not declare the speaker right or wrong. `sources` may not
    be empty for a retrieval-grounded note -- an uncited note is a note we
    cannot ship.
    """

    video_id: str
    timestamp: float
    claim_text: str
    note_text: str
    sources: list[Source] = Field(default_factory=list)


class Chapter(BaseModel):
    """Member 2's chapter boundary. Here only so the contract lives in one place."""

    video_id: str
    start: float
    title: str


# --------------------------------------------------------------------------
# Internal to retrieval
# --------------------------------------------------------------------------


class EvidencePassage(BaseModel):
    """One chunk of the evidence corpus, carrying enough provenance to cite."""

    passage_id: str
    doc_id: str
    title: str
    url: str
    revision_id: int | None = None
    section: str | None = None
    chunk_index: int = 0
    text: str

    def as_source(self) -> Source:
        return Source(
            title=self.title,
            url=self.url,
            revision_id=self.revision_id,
            section=self.section,
        )


class RetrievalResult(BaseModel):
    """A retrieved passage plus the score that surfaced it.

    `retriever` records which method produced the hit ("dense", "bm25",
    "hybrid") so ablations can be read straight off the results.
    """

    passage: EvidencePassage
    score: float
    retriever: str
