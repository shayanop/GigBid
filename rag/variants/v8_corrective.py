"""V8 corrective retrieval: grade evidence, re-search weak requirements, drop what fails the grade."""

from rag.pipeline import Components

COMPONENTS = Components(corrective=True)
