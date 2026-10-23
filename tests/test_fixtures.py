from rag.fixtures import context_worthy_claims, load_detections, load_segments


def test_fixtures_load_and_contracts_align():
    segs, dets = load_segments(), load_detections()
    assert len(segs) == len(dets)
    assert {s.segment_id for s in segs} == {d.segment_id for d in dets}


def test_detector_gate_selects_only_factual_claims():
    claims = context_worthy_claims()
    ids = {c.segment_id for c in claims}

    # Checkable factual assertions.
    assert "fx001-1" in ids  # Paris Agreement, 2015, two degrees
    assert "fx001-3" in ids  # 400 ppm CO2
    # Opinion and anecdote must not reach retrieval.
    assert "fx001-2" not in ids
    assert "fx001-4" not in ids


def test_segments_are_ordered_and_contiguous():
    segs = load_segments()
    for a, b in zip(segs, segs[1:]):
        assert a.end <= b.start
        assert a.duration > 0
