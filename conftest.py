import hashlib
import re
from functools import cache

import numpy as np
import pytest

from rag import retriever


class HashEmbedder:
    """Offline bag-of-words stand-in for the real embedding model in tests."""

    name = "hash-512"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(512, np.float32)
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 512] += 1
        return v / max(np.linalg.norm(v), 1e-12)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


@pytest.fixture
def offline_rag(monkeypatch, tmp_path):
    """Retrievers use HashEmbedder and a throwaway index folder."""
    monkeypatch.setattr(retriever, "INDEX_DIR", tmp_path / "index")
    # Replace the cached builder behind get_retriever's lock, not get_retriever itself.
    monkeypatch.setattr(retriever, "_cached", cache(lambda persona, variant:
                        retriever.build_retriever(persona, variant, HashEmbedder())))
    return HashEmbedder()
