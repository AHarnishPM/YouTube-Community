import pytest

from rag.models import EvidencePassage
from rag.retrieve import BM25Retriever, DenseRetriever, HybridRetriever, build_store

PASSAGES = [
    EvidencePassage(
        passage_id=f"d#{i}", doc_id="d", title="T", url="u",
        revision_id=1, chunk_index=i, text=t,
    )
    for i, t in enumerate([
        "The Paris Agreement is a treaty on climate change adopted in 2015.",
        "Solar power became the cheapest source of new electricity generation.",
        "Nuclear reactors produce electricity through controlled fission.",
    ])
]


@pytest.fixture(scope="module")
def retrievers():
    store = build_store(PASSAGES)
    dense = DenseRetriever(store)
    bm25 = BM25Retriever(PASSAGES)
    return dense, bm25, HybridRetriever(dense, bm25)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_empty_claim_raises(retrievers, blank):
    # An empty string still embeds, and dense search happily returns its
    # nearest neighbours. Those are noise the generator would cite as evidence.
    for r in retrievers:
        with pytest.raises(ValueError, match="empty claim"):
            r.retrieve(blank, 3)


def test_bm25_drops_zero_score_hits(retrievers):
    # A BM25 score of 0 means no query term appears in the passage at all --
    # not "weakly relevant", but literally unconnected.
    _, bm25, _ = retrievers
    assert bm25.retrieve("zzzxqv flurble wumpus", 3) == []

    hits = bm25.retrieve("paris agreement climate treaty", 3)
    assert hits and all(h.score > 0 for h in hits)


def test_hybrid_honours_k_larger_than_pool(retrievers):
    # Regression: pool capped the fused result silently (asked 99, got 60),
    # which would make a recall@k evaluation read short.
    _, _, hybrid = retrievers
    hits = hybrid.retrieve("electricity", k=3)
    assert len(hits) == min(3, len(PASSAGES))


def test_dense_caps_at_corpus_size(retrievers):
    dense, _, _ = retrievers
    assert len(dense.retrieve("electricity", 9999)) == len(PASSAGES)


def test_fetch_article_cannot_be_asked_for_a_revision():
    # Guard against reintroducing the wikitext bug: the plaintext extract is
    # only served for current revisions, so a revision_id parameter would be
    # a lie. See rag/corpus/wikipedia.py.
    import inspect

    from rag.corpus.wikipedia import fetch_article

    assert "revision_id" not in inspect.signature(fetch_article).parameters


def test_saving_an_empty_index_raises():
    # Used to write passages.jsonl with no vectors.npy, so the later load
    # failed with "no saved index" -- blaming the read for a bad write.
    import tempfile
    from pathlib import Path

    from rag.store.numpy_store import NumpyVectorStore

    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError, match="empty index"):
            NumpyVectorStore().save(Path(td))


def test_hybrid_falls_back_to_dense_when_bm25_finds_nothing(retrievers):
    # Dropping zero-score BM25 hits (bug 3) made empty runs possible, so RRF
    # has to tolerate one.
    _, bm25, hybrid = retrievers
    assert bm25.retrieve("zzzxqv flurble wumpus", 3) == []
    assert len(hybrid.retrieve("zzzxqv flurble wumpus", 3)) > 0
