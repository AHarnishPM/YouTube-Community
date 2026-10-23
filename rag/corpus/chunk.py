"""Split article text into retrievable passages that carry their provenance.

Why chunking matters here: a note must cite the evidence it rests on, so the
unit we retrieve has to be small enough to be a real citation (pointing a
viewer at a whole Wikipedia article is not evidence) and large enough to stand
alone when the model reads it. A few hundred words, overlapping, is the
standard compromise and what we start with.

Section headings are tracked because they sharpen a citation: "Climate change
-> Effects" tells a viewer far more than the article title alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag.models import EvidencePassage

# `explaintext` extracts from the MediaWiki API mark sections with wiki-style
# headings: "== History ==", "=== Early years ===".
_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1$")

# Sections that are navigation or bookkeeping, not evidence.
_SKIP_SECTIONS = {
    "see also",
    "references",
    "further reading",
    "external links",
    "notes",
    "bibliography",
    "sources",
    "citations",
}

# Sized to stay inside the embedding model's 256-token window: ~150 English
# words is roughly 200 word-pieces, leaving headroom. Overshooting does not
# error, it silently truncates -- the tail of a passage would be
# unsearchable, which is the worst kind of bug because retrieval still
# "works". Verify with rag.embed.check_chunk_budget().
TARGET_WORDS = 150
OVERLAP_WORDS = 35
MIN_WORDS = 30


@dataclass
class _Para:
    section: str | None
    text: str


def _parse_paragraphs(text: str) -> list[_Para]:
    """Flatten article text into paragraphs tagged with their section.

    Skipping is *depth-aware*: entering "== References ==" skips everything
    until the next heading at the same or shallower level, so subsections like
    "=== Cited works ===" are skipped with their parent. Tracking only the
    current section name would let those subsections back in, because their own
    names are not in the skip list -- and citation lists are dense with proper
    nouns, so they score misleadingly well on entity-heavy claims.
    """
    out: list[_Para] = []
    section: str | None = None
    skip_depth: int | None = None  # heading level that opened a skipped region

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            name = heading.group(2).strip()

            # A heading at the same or shallower level closes the skipped region.
            if skip_depth is not None and level <= skip_depth:
                skip_depth = None
            if skip_depth is None and name.lower() in _SKIP_SECTIONS:
                skip_depth = level

            section = name
            continue

        if skip_depth is not None:
            continue

        out.append(_Para(section=section, text=line))

    return out


def chunk_article(
    *,
    doc_id: str,
    title: str,
    url: str,
    text: str,
    revision_id: int | None = None,
    target_words: int = TARGET_WORDS,
    overlap_words: int = OVERLAP_WORDS,
    min_words: int = MIN_WORDS,
) -> list[EvidencePassage]:
    """Chunk one article into overlapping passages.

    Each section's text is windowed into passages of at most `target_words`,
    stepping by `target_words - overlap_words` so consecutive passages share
    `overlap_words` of context. A claim whose evidence straddles a boundary
    therefore still lands whole inside some passage.

    Chunks never span a section boundary: mixing two sections into one passage
    would make the citation's section label a lie.
    """
    # A misconfiguration here yields an empty index rather than an error,
    # which looks identical to "the article had no usable text".
    if min_words > target_words:
        raise ValueError(
            f"min_words ({min_words}) exceeds target_words ({target_words}): "
            "no chunk could ever qualify"
        )
    if overlap_words >= target_words:
        raise ValueError(
            f"overlap_words ({overlap_words}) must be smaller than "
            f"target_words ({target_words}), or chunking cannot advance"
        )

    passages: list[EvidencePassage] = []
    paragraphs = _parse_paragraphs(text)

    stride = target_words - overlap_words

    def emit(words: list[str], section: str | None) -> None:
        body = " ".join(words).strip()
        if len(words) < min_words:
            return
        idx = len(passages)
        passages.append(
            EvidencePassage(
                passage_id=f"{doc_id}#{idx}",
                doc_id=doc_id,
                title=title,
                url=url,
                revision_id=revision_id,
                section=section,
                chunk_index=idx,
                text=body,
            )
        )

    def flush_section(words: list[str], section: str | None) -> None:
        """Window one section's words into overlapping passages.

        Windowing rather than paragraph accumulation because a single
        Wikipedia paragraph can exceed the target on its own -- the API's
        plaintext extract puts each paragraph on one line, so paragraph-at-a-
        time chunking cannot bound passage size.
        """
        if not words:
            return
        if len(words) <= target_words:
            emit(words, section)
            return

        pos = 0
        while pos < len(words):
            window = words[pos : pos + target_words]
            # Fold a runt tail into the previous window instead of emitting
            # a fragment too small to carry evidence.
            if len(window) < min_words and passages:
                break
            emit(window, section)
            if pos + target_words >= len(words):
                break
            pos += stride

    buf: list[str] = []
    buf_section: str | None = None

    for para in paragraphs:
        if para.section != buf_section:
            flush_section(buf, buf_section)
            buf = []
            buf_section = para.section
        buf.extend(para.text.split())

    flush_section(buf, buf_section)
    return passages
