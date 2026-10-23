"""Pooled relevance labels for retrieval evaluation.

## Why pooling

Judging all 457 passages against each of 50 claims is 22,850 decisions -- not
happening by hand. The standard answer (TREC's, since 1992) is **pooling**:
run every retriever, take the union of their top-N, and judge only that pool.
About 20-30 passages per claim, which is a few hours of work rather than weeks.

The cost is explicit: a relevant passage that *no* retriever surfaced is never
judged, and unjudged passages count as not relevant. So pooled recall is an
upper bound on true recall. That is a known, citable limitation of the method,
not a flaw in this implementation -- but it must be stated in the report.

Pooling across all three retrievers (rather than just the one under test) is
what keeps the comparison fair: if only dense results were pooled, BM25 would
be penalised for finding relevant passages that were never judged.

## Why passages are keyed by content hash

`passage_id` embeds a chunk index, which shifts whenever chunking changes --
fixing the bibliography-leak bug moved the corpus from 458 to 457 passages and
renumbered everything after the leak. Labels keyed on those ids would have
silently pointed at the wrong passages. A hash of the passage text survives
reindexing, and survives a corpus re-fetch as long as the article text is
unchanged.

If chunk size or overlap changes, the passage boundaries change, so the keys
change and the pool must be rebuilt. Unavoidable, and loud rather than silent:
`eval` reports how many labelled keys it could not find.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rag.models import EvidencePassage

LABELS_PATH = Path("data/eval/labels.json")

_WS = re.compile(r"\s+")


def passage_key(text: str) -> str:
    """Stable 12-hex-char key for a passage, from its normalised text."""
    normalised = _WS.sub(" ", text).strip().lower()
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:12]


@dataclass
class Candidate:
    key: str
    title: str
    section: str | None
    snippet: str
    relevant: bool | None = None          # None = not yet judged
    retrievers: list[str] = field(default_factory=list)


@dataclass
class ClaimLabels:
    claim_id: str
    claim_text: str
    candidates: list[Candidate]

    @property
    def relevant_keys(self) -> set[str]:
        return {c.key for c in self.candidates if c.relevant is True}

    @property
    def judged(self) -> int:
        return sum(1 for c in self.candidates if c.relevant is not None)

    @property
    def is_complete(self) -> bool:
        return self.judged == len(self.candidates)


@dataclass
class LabelSet:
    claims: list[ClaimLabels]
    pool_depth: int
    provisional: bool = True
    note: str = ""

    @property
    def usable(self) -> list[ClaimLabels]:
        """Claims with at least one relevant passage.

        Claims whose pool contains nothing relevant are undefined for recall
        and nDCG, so they are excluded rather than scored as zero -- counting
        them as misses would blame the retriever for a gap in the corpus.
        """
        return [c for c in self.claims if c.relevant_keys]

    # ---- persistence ----

    def save(self, path: Path = LABELS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "provisional": self.provisional,
                    "note": self.note,
                    "pool_depth": self.pool_depth,
                    "claims": [
                        {
                            "claim_id": c.claim_id,
                            "claim_text": c.claim_text,
                            "candidates": [
                                {
                                    "key": d.key,
                                    "title": d.title,
                                    "section": d.section,
                                    "snippet": d.snippet,
                                    "retrievers": d.retrievers,
                                    "relevant": d.relevant,
                                }
                                for d in c.candidates
                            ],
                        }
                        for c in self.claims
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path = LABELS_PATH) -> "LabelSet":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            provisional=data.get("provisional", True),
            note=data.get("note", ""),
            pool_depth=data.get("pool_depth", 0),
            claims=[
                ClaimLabels(
                    claim_id=c["claim_id"],
                    claim_text=c["claim_text"],
                    candidates=[
                        Candidate(
                            key=d["key"],
                            title=d["title"],
                            section=d.get("section"),
                            snippet=d.get("snippet", ""),
                            relevant=d.get("relevant"),
                            retrievers=d.get("retrievers", []),
                        )
                        for d in c["candidates"]
                    ],
                )
                for c in data["claims"]
            ],
        )


def build_pool(
    claims: list[tuple[str, str]],
    retrievers: dict,
    *,
    depth: int = 10,
) -> LabelSet:
    """Build a labeling worksheet: union of every retriever's top-`depth`.

    `claims` is [(claim_id, claim_text)].
    """
    out: list[ClaimLabels] = []

    for claim_id, claim_text in claims:
        seen: dict[str, Candidate] = {}
        for name, retriever in retrievers.items():
            for hit in retriever.retrieve(claim_text, depth):
                p: EvidencePassage = hit.passage
                key = passage_key(p.text)
                if key not in seen:
                    body = _WS.sub(" ", p.text).strip()
                    seen[key] = Candidate(
                        key=key,
                        title=p.title,
                        section=p.section,
                        snippet=body[:240],
                    )
                if name not in seen[key].retrievers:
                    seen[key].retrievers.append(name)

        out.append(
            ClaimLabels(
                claim_id=claim_id,
                claim_text=claim_text,
                candidates=list(seen.values()),
            )
        )

    return LabelSet(claims=out, pool_depth=depth)
