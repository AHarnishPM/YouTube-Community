"""Sentence embeddings for claims and evidence passages.

Model choice (DESIGN-LOG): `all-MiniLM-L6-v2`. 384 dimensions, runs on CPU in
reasonable time, and is the standard baseline for sentence similarity work --
which matters because the project's claim is about *retrieval quality*, not
about having picked an exotic encoder. Pinned by name so results do not drift.

The one sharp edge is the 256 word-piece input limit: anything longer is
truncated silently. `check_chunk_budget` asserts our chunk size fits, so that
failure shows up as a test rather than as mysteriously poor recall.
"""

from __future__ import annotations

import logging
import os

import numpy as np

# Quiet the library chatter before anything imports torch or transformers.
# Three unrelated sources each print something on every single command: a
# torch warning about macOS redirects, a HuggingFace note about
# unauthenticated requests, and a weight-loading progress bar. None of it is
# actionable here, and all of it buries the output we actually print -- which
# matters when the output is being read aloud in a demo.
#
# Set `RAG_VERBOSE=1` to get it all back when debugging a model or download
# problem.
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


# Lines the libraries print on every run that say nothing actionable. Matched
# as substrings, and ONLY while the encoder is loading -- anything else on
# stderr is passed straight through, so a real failure is never hidden.
_BENIGN_STDERR = (
    "sending unauthenticated requests",
    "Redirects are currently not supported",
    "Could not reach the Hub",
    "Using cached commit hash",
    "TOKENIZERS_PARALLELISM",
)


if not os.environ.get("RAG_VERBOSE"):
    # Decided before any HuggingFace import, because the hub notice is printed
    # at import time -- setting this later is too late. With the encoder
    # cached there is nothing to fetch, so offline loading means no network
    # round-trip, clean output, and a demo that works without wifi.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    for _name in (
        "torch.distributed.elastic.multiprocessing.redirects",
        "huggingface_hub",
        "huggingface_hub.file_download",
        "transformers",
        "sentence_transformers",
    ):
        logging.getLogger(_name).setLevel(logging.ERROR)

_model = None


def get_model():
    """Load the encoder once per process (loading is the expensive part)."""
    global _model
    if _model is not None:
        return _model

    if os.environ.get("RAG_VERBOSE"):
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
        return _model

    import contextlib
    import io
    import sys

    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            from sentence_transformers import SentenceTransformer

            try:
                from transformers.utils import logging as hf_logging

                hf_logging.disable_progress_bar()
                hf_logging.set_verbosity_error()
            except Exception:
                pass

            _model = SentenceTransformer(MODEL_NAME)
    finally:
        # Re-emit anything that was not on the known-benign list, so a genuine
        # error during loading still reaches the user.
        for line in captured.getvalue().splitlines():
            if line.strip() and not any(b in line for b in _BENIGN_STDERR):
                print(line, file=sys.stderr)

    return _model


def embed_texts(texts: list[str], *, batch_size: int = 64) -> np.ndarray:
    """Encode texts to L2-normalised vectors.

    Normalising means cosine similarity is a plain dot product, which keeps the
    brute-force store simple and makes scores comparable across retrievers.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)

    vecs = get_model().encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 500,
    )
    return np.asarray(vecs, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]


def check_chunk_budget(target_words: int | None = None) -> dict:
    """Confirm a target chunk size survives the encoder without truncation.

    Returns the measured numbers rather than just asserting, so the margin is
    visible and can be recorded in the design log.
    """
    from rag.corpus.chunk import TARGET_WORDS

    target = target_words or TARGET_WORDS
    model = get_model()
    limit = model.max_seq_length

    # Realistic English rather than repeated tokens: word-piece counts depend
    # on how often words split, and real prose splits more than "word word".
    sample = (
        "The Paris Agreement is an international treaty on climate change "
        "adopted in 2015, covering mitigation, adaptation and finance. "
    ) * 40
    words = sample.split()[:target]

    tokens = len(model.tokenizer.tokenize(" ".join(words)))
    return {
        "target_words": target,
        "measured_tokens": tokens,
        "model_limit": limit,
        "fits": tokens <= limit,
        "headroom_tokens": limit - tokens,
    }
