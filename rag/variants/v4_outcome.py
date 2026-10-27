"""V4 outcome-aware ranking: proposals that won or got replies, and their projects, rank higher."""

from rag.pipeline import Components

COMPONENTS = Components(outcome=True)
