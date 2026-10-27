"""V1 requirement decomposition: search each requirement in the post and fuse the rankings."""

from rag.pipeline import Components

COMPONENTS = Components(decompose=True)
