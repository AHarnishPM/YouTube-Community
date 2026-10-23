import math

import pytest

from rag.eval.metrics import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank

RANKED = ["a", "b", "c", "d", "e"]
REL = {"a", "d", "z"}          # "z" is relevant but never retrieved


class TestRecall:
    def test_counts_only_within_k(self):
        assert recall_at_k(RANKED, REL, 1) == pytest.approx(1 / 3)   # a
        assert recall_at_k(RANKED, REL, 4) == pytest.approx(2 / 3)   # a, d
        assert recall_at_k(RANKED, REL, 5) == pytest.approx(2 / 3)   # z unreachable

    def test_perfect_and_zero(self):
        assert recall_at_k(["a", "d"], {"a", "d"}, 2) == 1.0
        assert recall_at_k(["x", "y"], {"a"}, 2) == 0.0

    def test_undefined_without_labels(self):
        with pytest.raises(ValueError):
            recall_at_k(RANKED, set(), 5)


class TestPrecision:
    def test_divides_by_k(self):
        assert precision_at_k(RANKED, REL, 5) == pytest.approx(2 / 5)
        assert precision_at_k(RANKED, REL, 1) == 1.0

    def test_short_result_is_penalised_not_rewarded(self):
        # Returning 1 hit when asked for 5 must not score as precision 1.0.
        assert precision_at_k(["a"], {"a"}, 5) == pytest.approx(1 / 5)

    def test_k_must_be_positive(self):
        with pytest.raises(ValueError):
            precision_at_k(RANKED, REL, 0)


class TestReciprocalRank:
    def test_rank_of_first_hit(self):
        assert reciprocal_rank(RANKED, {"a"}) == 1.0
        assert reciprocal_rank(RANKED, {"b"}) == 0.5
        assert reciprocal_rank(RANKED, {"d"}) == pytest.approx(1 / 4)

    def test_takes_the_earliest_of_several(self):
        assert reciprocal_rank(RANKED, {"d", "b"}) == 0.5

    def test_zero_when_absent(self):
        assert reciprocal_rank(RANKED, {"zzz"}) == 0.0


class TestNDCG:
    def test_perfect_ranking_is_one(self):
        assert ndcg_at_k(["a", "d"], {"a", "d"}, 2) == pytest.approx(1.0)

    def test_rewards_earlier_hits(self):
        early = ndcg_at_k(["a", "x", "y"], {"a"}, 3)
        late = ndcg_at_k(["x", "y", "a"], {"a"}, 3)
        assert early > late
        assert early == pytest.approx(1.0)
        assert late == pytest.approx(1.0 / math.log2(4))

    def test_zero_when_nothing_relevant_retrieved(self):
        assert ndcg_at_k(["x", "y"], {"a"}, 2) == 0.0

    def test_ideal_is_capped_at_k(self):
        # 3 relevant but k=1: retrieving one at rank 1 is the best possible.
        assert ndcg_at_k(["a", "d", "z"], {"a", "d", "z"}, 1) == pytest.approx(1.0)

    def test_undefined_without_labels(self):
        with pytest.raises(ValueError):
            ndcg_at_k(RANKED, set(), 5)
