# Fixtures

Hand-written stand-ins for the two upstream contracts this component consumes:

- `transcript_segments.json` — what Member 1's ingestion will put in Postgres
- `claim_detections.json` — what Member 2's detector will hand to retrieval

These exist so the retrieval pipeline can be built and measured before either
teammate's side lands (see DESIGN-LOG D-02). They are **not** evaluation data:
the retrieval eval set is built separately from real videos in `data/`.

Segments imitate auto-generated YouTube captions on purpose — lowercase, no
sentence-final punctuation — because that is the input the real system gets,
and clean prose would make the pipeline look better than it is.
