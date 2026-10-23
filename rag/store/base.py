"""The vector-store boundary (DESIGN-LOG D-02).

The proposal's plan of action said "embeddings with PostgreSQL vector search",
but Member 1's Postgres does not exist yet and this component does not need it:
retrieval maps claim text to evidence passages, and the evidence corpus is
ours. So we build against a local store now and swap in pgvector later.

This Protocol is what makes that swap cheap. Keep it narrow -- anything that
leaks Postgres or NumPy specifics into callers defeats the purpose.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from rag.models import EvidencePassage


class VectorStore(Protocol):
    def add(self, passages: list[EvidencePassage], vectors: np.ndarray) -> None:
        """Index passages alongside their embedding vectors."""
        ...

    def search(self, query: np.ndarray, k: int) -> list[tuple[EvidencePassage, float]]:
        """Return the k nearest passages with their similarity scores."""
        ...

    def __len__(self) -> int: ...
