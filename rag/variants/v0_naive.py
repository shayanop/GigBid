"""V0 baseline: fixed-size chunks, dense embeddings, top-k cosine over the full job post."""

from functools import partial

from rag import retriever
from rag.index.vector import VectorIndex, build_index, fast_embedder
from rag.ingest.loaders import fixed_chunks


def build(persona: str, embedder=None) -> VectorIndex:
    cfg = retriever.rag_config()
    size, overlap = cfg["chunk_size"], cfg["chunk_overlap"]
    return build_index(retriever.PERSONAS_DIR / persona, retriever.INDEX_DIR / "v0" / persona,
                       embedder or fast_embedder(cfg["embedding_model"]),
                       partial(fixed_chunks, size=size, overlap=overlap),
                       chunker_key=f"fixed-{size}-{overlap}")
