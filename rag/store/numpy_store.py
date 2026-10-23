"""Brute-force cosine search over an in-memory matrix.

Deliberately the dumbest thing that works. At our corpus size -- hundreds of
articles, order 10k passages -- an exact dot product over a 10k x 384 matrix is
a few milliseconds, so an approximate index (FAISS, HNSW) would add a
dependency and an accuracy caveat to buy speed we do not need.

It is also exact, which is worth something when the thing being measured *is*
retrieval quality: no recall lost to index approximation means a disappointing
recall@k number is the retriever's fault, not the index's.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from rag.models import EvidencePassage


class NumpyVectorStore:
    def __init__(self) -> None:
        self._passages: list[EvidencePassage] = []
        self._matrix: np.ndarray | None = None

    def add(self, passages: list[EvidencePassage], vectors: np.ndarray) -> None:
        if len(passages) != len(vectors):
            raise ValueError(
                f"{len(passages)} passages but {len(vectors)} vectors"
            )
        if not passages:
            return

        self._passages.extend(passages)
        block = np.asarray(vectors, dtype=np.float32)
        self._matrix = (
            block if self._matrix is None else np.vstack([self._matrix, block])
        )

    def search(self, query: np.ndarray, k: int) -> list[tuple[EvidencePassage, float]]:
        if self._matrix is None or not self._passages:
            return []

        # Vectors are L2-normalised upstream, so a dot product *is* cosine.
        scores = self._matrix @ np.asarray(query, dtype=np.float32)
        k = min(k, len(self._passages))

        # argpartition for the top-k, then sort just those.
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]

        return [(self._passages[i], float(scores[i])) for i in top]

    def __len__(self) -> int:
        return len(self._passages)

    @property
    def passages(self) -> list[EvidencePassage]:
        """The indexed passages, in index order.

        Exposed so BM25 can be rebuilt from a saved index without
        re-reading the corpus -- the lexical retriever needs the same
        passage set the dense one was built from, or the comparison is
        not a comparison.
        """
        return list(self._passages)

    # ---- persistence: embedding a corpus is slow, so never do it twice ----

    def save(self, directory: Path) -> None:
        # Refuse rather than write half an index. An empty store wrote
        # passages.jsonl but no vectors.npy, so the later load failed with
        # "no saved index" -- pointing at the read when the write was at
        # fault. An empty index is always a symptom of something upstream
        # (every fetch failed, or chunking produced nothing), so say so here.
        if self._matrix is None or not self._passages:
            raise ValueError(
                "refusing to save an empty index: no passages were embedded "
                "(check that the corpus fetched and chunked correctly)"
            )

        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self._matrix)
        with (directory / "passages.jsonl").open("w", encoding="utf-8") as fh:
            for p in self._passages:
                fh.write(p.model_dump_json() + "\n")

    @classmethod
    def load(cls, directory: Path) -> "NumpyVectorStore":
        store = cls()
        vec_path = directory / "vectors.npy"
        pas_path = directory / "passages.jsonl"
        if not vec_path.exists() or not pas_path.exists():
            raise FileNotFoundError(f"no saved index in {directory}")

        store._matrix = np.load(vec_path)
        with pas_path.open(encoding="utf-8") as fh:
            store._passages = [
                EvidencePassage(**json.loads(line)) for line in fh if line.strip()
            ]

        if len(store._passages) != len(store._matrix):
            raise ValueError("index is corrupt: passage/vector count mismatch")
        return store
