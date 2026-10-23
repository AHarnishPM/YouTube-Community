import tempfile
from pathlib import Path

import pytest

from rag.eval.labels import Candidate, ClaimLabels, LabelSet, build_pool, passage_key
from rag.eval.run import evaluate
from rag.models import EvidencePassage, RetrievalResult


class TestPassageKey:
    def test_is_stable_under_whitespace_and_case(self):
        # Keys must survive re-chunking and re-fetching; only the words matter.
        assert passage_key("The  Paris\nAgreement ") == passage_key("the paris agreement")

    def test_differs_for_different_text(self):
        assert passage_key("solar power") != passage_key("nuclear power")

    def test_does_not_depend_on_chunk_index(self):
        # The bug this guards against: labels keyed on passage_id broke when
        # fixing the bibliography leak renumbered every chunk after it.
        a = EvidencePassage(passage_id="d#3", doc_id="d", title="T", url="u",
                            chunk_index=3, text="same words here")
        b = EvidencePassage(passage_id="d#7", doc_id="d", title="T", url="u",
                            chunk_index=7, text="same words here")
        assert passage_key(a.text) == passage_key(b.text)


def _passage(i, text):
    return EvidencePassage(passage_id=f"d#{i}", doc_id="d", title=f"Art{i}",
                           url="u", chunk_index=i, text=text)


class _Fake:
    """A retriever returning a fixed list, for testing the harness itself."""

    def __init__(self, name, passages):
        self.name = name
        self._passages = passages

    def retrieve(self, claim, k):
        return [
            RetrievalResult(passage=p, score=1.0 - i / 100, retriever=self.name)
            for i, p in enumerate(self._passages[:k])
        ]


class TestPooling:
    def test_pool_is_the_union_across_retrievers(self):
        a, b, c = _passage(1, "alpha"), _passage(2, "beta"), _passage(3, "gamma")
        pool = build_pool(
            [("c1", "a claim")],
            {"r1": _Fake("r1", [a, b]), "r2": _Fake("r2", [b, c])},
            depth=10,
        )
        keys = {cand.key for cand in pool.claims[0].candidates}
        assert keys == {passage_key("alpha"), passage_key("beta"), passage_key("gamma")}

    def test_records_which_retrievers_found_each_passage(self):
        shared = _passage(1, "alpha")
        pool = build_pool(
            [("c1", "a claim")],
            {"r1": _Fake("r1", [shared]), "r2": _Fake("r2", [shared])},
            depth=10,
        )
        assert pool.claims[0].candidates[0].retrievers == ["r1", "r2"]

    def test_starts_unjudged(self):
        pool = build_pool([("c1", "x")], {"r1": _Fake("r1", [_passage(1, "alpha")])})
        assert pool.claims[0].candidates[0].relevant is None
        assert pool.claims[0].judged == 0
        assert not pool.claims[0].is_complete


class TestLabelSet:
    def _set(self):
        return LabelSet(pool_depth=5, claims=[
            ClaimLabels("judged", "x", [Candidate("k1", "T", None, "s", relevant=True)]),
            ClaimLabels("unjudged", "y", [Candidate("k2", "T", None, "s", relevant=None)]),
            ClaimLabels("none-relevant", "z", [Candidate("k3", "T", None, "s", relevant=False)]),
        ])

    def test_usable_excludes_unjudged_and_no_relevant(self):
        # Scoring a claim with no relevant passages as 0 would blame the
        # retriever for a gap in the corpus or the labels.
        assert [c.claim_id for c in self._set().usable] == ["judged"]

    def test_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "labels.json"
            self._set().save(p)
            back = LabelSet.load(p)
            assert [c.claim_id for c in back.claims] == ["judged", "unjudged", "none-relevant"]
            assert back.claims[0].relevant_keys == {"k1"}
            assert back.claims[1].candidates[0].relevant is None


class TestEvaluate:
    def test_refuses_to_score_with_nothing_usable(self):
        empty = LabelSet(pool_depth=5, claims=[
            ClaimLabels("c", "x", [Candidate("k", "T", None, "s", relevant=None)])
        ])
        with pytest.raises(ValueError, match="no usable claims"):
            evaluate(empty, {"r": _Fake("r", [])})

    def test_scores_a_perfect_retriever_at_one(self):
        hit = _passage(1, "the relevant passage")
        labels = LabelSet(pool_depth=5, claims=[
            ClaimLabels("c1", "a claim", [
                Candidate(passage_key(hit.text), "Art1", None, "s", relevant=True)
            ])
        ])
        scores, diag = evaluate(labels, {"perfect": _Fake("perfect", [hit])}, ks=(1,))
        assert scores[0].recall[1] == 1.0
        assert scores[0].mrr == 1.0
        assert diag["claims_usable"] == 1

    def test_detects_stale_labels(self):
        # A labelled key no retriever returns means the pool is out of date --
        # the usual cause is changed chunking. It must be reported, not
        # silently deflate recall.
        labels = LabelSet(pool_depth=5, claims=[
            ClaimLabels("c1", "a claim", [
                Candidate(passage_key("text that moved"), "Art1", None, "s", relevant=True)
            ])
        ])
        _, diag = evaluate(labels, {"r": _Fake("r", [_passage(9, "different text")])}, ks=(1,))
        assert diag["stale_keys"] == 1
