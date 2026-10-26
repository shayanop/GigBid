"""Dense vector index with incremental rebuilds (B1).

ponytail: brute-force cosine over a numpy matrix; a persona has ~1k chunks, so
this is exact and sub-millisecond. Move to pgvector past ~100k chunks.
"""

import hashlib
import json
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Protocol

import numpy as np

from rag.ingest.loaders import load_persona
from rag.schema import Chunk, Document, Evidence


class Embedder(Protocol):
    name: str
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _unit(m: np.ndarray) -> np.ndarray:
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)


class FastEmbedder:
    """Open embedding model on CPU via fastembed (ONNX)."""

    def __init__(self, model: str):
        from fastembed import TextEmbedding
        self.name, self._model = model, TextEmbedding(model)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _unit(np.array(list(self._model.passage_embed(texts)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return _unit(np.array(next(iter(self._model.query_embed(text))), dtype=np.float32))


@cache
def fast_embedder(model: str) -> FastEmbedder:
    return FastEmbedder(model)


class VectorIndex:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray, embedder: Embedder):
        self.chunks, self.vectors, self.embedder = chunks, vectors, embedder

    def search(self, query: str, k: int = 5,
               where: Callable[[Chunk], bool] | None = None) -> list[Evidence]:
        if not self.chunks:
            return []
        scores = self.vectors @ self.embedder.embed_query(query)
        hits = []
        for i in np.argsort(-scores):
            if where is None or where(self.chunks[i]):
                hits.append(Evidence(**self.chunks[i].model_dump(), score=float(scores[i])))
                if len(hits) == k:
                    break
        return hits


def _hash(doc: Document) -> str:
    return hashlib.sha256(doc.model_dump_json().encode()).hexdigest()


def build_index(persona_dir: Path, index_dir: Path, embedder: Embedder,
                chunker: Callable[[Document], list[Chunk]], chunker_key: str) -> VectorIndex:
    """Loads the persona, re-embedding only documents that are new or changed since
    the last build in index_dir. Removed documents drop out."""
    docs = load_persona(persona_dir)
    manifest_path = index_dir / "manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    reusable: dict[str, list[tuple[Chunk, np.ndarray]]] = {}
    if old.get("embedder") == embedder.name and old.get("chunker") == chunker_key:
        lines = (index_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        vectors = np.load(index_dir / "vectors.npy")
        for line, vec in zip(lines, vectors, strict=True):
            chunk = Chunk.model_validate_json(line)
            reusable.setdefault(chunk.doc_id, []).append((chunk, vec))

    hashes, rows, fresh = {}, [], []
    for doc in docs:
        hashes[doc.id] = _hash(doc)
        if old.get("docs", {}).get(doc.id) == hashes[doc.id] and doc.id in reusable:
            rows.extend(reusable[doc.id])
        else:
            fresh.extend(chunker(doc))
    if fresh:
        new_vectors = embedder.embed_documents([c.text for c in fresh])
        rows.extend(zip(fresh, new_vectors, strict=True))

    chunks = [c for c, _ in rows]
    dim = rows[0][1].shape[0] if rows else 0
    vectors = np.stack([v for _, v in rows]) if rows else np.zeros((0, dim), np.float32)
    index_dir.mkdir(parents=True, exist_ok=True)
    np.save(index_dir / "vectors.npy", vectors)
    (index_dir / "chunks.jsonl").write_text(
        "".join(c.model_dump_json() + "\n" for c in chunks), encoding="utf-8")
    manifest_path.write_text(json.dumps(
        {"embedder": embedder.name, "chunker": chunker_key, "docs": hashes,
         "embedded_chunks": len(fresh)}, indent=1))
    return VectorIndex(chunks, vectors, embedder)
