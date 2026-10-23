from rag.corpus.chunk import chunk_article


def _chunk(text, **kw):
    return chunk_article(
        doc_id="wiki:Test@1", title="Test", url="http://x/Test",
        text=text, revision_id=1, **kw
    )


def test_provenance_is_carried_on_every_passage():
    text = "== History ==\n" + " ".join(["word"] * 400)
    passages = _chunk(text)

    assert passages
    for p in passages:
        assert p.title == "Test"
        assert p.revision_id == 1
        assert p.section == "History"
        # A passage that cannot be cited is useless to us.
        assert p.as_source().url


def test_chunks_do_not_span_sections():
    text = (
        "== Alpha ==\n" + " ".join(["a"] * 300) + "\n"
        "== Beta ==\n" + " ".join(["b"] * 300)
    )
    for p in _chunk(text):
        words = set(p.text.split())
        assert not ({"a"} <= words and {"b"} <= words), "section bleed"


def test_navigation_sections_are_dropped():
    text = (
        "== Real ==\n" + " ".join(["keep"] * 100) + "\n"
        "== References ==\n" + " ".join(["drop"] * 100) + "\n"
        "== External links ==\n" + " ".join(["drop"] * 100)
    )
    assert all("drop" not in p.text for p in _chunk(text))


def test_overlap_links_adjacent_chunks():
    text = "== S ==\n" + " ".join(f"w{i}" for i in range(600))
    passages = _chunk(text, target_words=100, overlap_words=20)

    assert len(passages) > 1
    first_tail = passages[0].text.split()[-20:]
    assert set(first_tail) & set(passages[1].text.split())


def test_short_trailing_fragment_is_dropped():
    # Below min_words a passage carries no evidence; it should not be emitted.
    assert _chunk("== S ==\ntoo short", min_words=30) == []


def test_lead_section_has_no_heading():
    passages = _chunk(" ".join(["lead"] * 100))
    assert passages and passages[0].section is None


def test_single_long_paragraph_is_split():
    # Regression: the MediaWiki plaintext extract puts each paragraph on one
    # line, so a long paragraph used to pass through as one oversized passage
    # and be silently truncated by the embedding model.
    text = "== S ==\n" + " ".join(f"w{i}" for i in range(600))
    passages = _chunk(text, target_words=100, overlap_words=20)

    assert len(passages) > 1
    assert all(len(p.text.split()) <= 100 for p in passages)


def test_no_passage_exceeds_target():
    import random
    random.seed(0)
    paras = [" ".join(f"w{random.randint(0, 99)}" for _ in range(random.randint(5, 500)))
             for _ in range(8)]
    text = "== S ==\n" + "\n".join(paras)

    for p in _chunk(text, target_words=150, overlap_words=35):
        assert len(p.text.split()) <= 150


def test_subsection_under_skipped_section_is_dropped():
    # Regression: tracking only the current section name let subsections of
    # "References" back in, because "Cited works" is not itself in the skip
    # list. Citation lists are dense with proper nouns, so they scored
    # misleadingly well on entity-heavy claims.
    text = (
        "== Real ==\n" + " ".join(["keep"] * 80) + "\n"
        "== References ==\n" + " ".join(["drop"] * 80) + "\n"
        "=== Cited works ===\n" + " ".join(["leak"] * 80)
    )
    body = " ".join(p.text for p in _chunk(text))
    assert "keep" in body
    assert "drop" not in body
    assert "leak" not in body


def test_skipped_region_closes_at_same_or_shallower_heading():
    text = (
        "== References ==\n" + " ".join(["drop"] * 80) + "\n"
        "=== Sub ===\n" + " ".join(["drop"] * 80) + "\n"
        "== History ==\n" + " ".join(["resume"] * 80)
    )
    body = " ".join(p.text for p in _chunk(text))
    assert "drop" not in body
    assert "resume" in body


def test_impossible_size_config_raises_instead_of_yielding_nothing():
    # Both of these used to return [] silently, which is indistinguishable
    # from "the article had no usable text".
    import pytest

    with pytest.raises(ValueError, match="min_words"):
        _chunk("== S ==\n" + " ".join(["w"] * 300), target_words=50, min_words=200)

    with pytest.raises(ValueError, match="overlap_words"):
        _chunk("== S ==\n" + " ".join(["w"] * 300), target_words=100, overlap_words=100)
