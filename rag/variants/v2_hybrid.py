"""V2 hybrid retrieval: BM25 keyword ranking fused with dense ranking (exact technologies)."""

from rag.pipeline import Components

COMPONENTS = Components(hybrid=True)
