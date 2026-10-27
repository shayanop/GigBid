"""V3 cross-encoder reranking of the top candidates (precision at small k)."""

from rag.pipeline import Components

COMPONENTS = Components(rerank=True)
