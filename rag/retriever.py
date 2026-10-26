"""Retriever factory: picks the variant named in agent/config.yaml (rag.variant).

Every variant module in rag/variants exposes build(persona, embedder=None)
returning an object with search(query, k, where) -> list[Evidence].
"""

import importlib
import threading
from functools import cache
from pathlib import Path

from agent.config import load_config

ROOT = Path(__file__).resolve().parents[1]
PERSONAS_DIR = ROOT / "data" / "personas"
INDEX_DIR = ROOT / "data" / "processed" / "index"
VARIANTS = {"v0": "v0_naive"}


def rag_config() -> dict:
    return load_config()["rag"]


def build_retriever(persona: str, variant: str | None = None, embedder=None):
    """Builds (incrementally) and returns the retriever; call again after uploads."""
    name = variant or rag_config()["variant"]
    return importlib.import_module(f"rag.variants.{VARIANTS[name]}").build(persona, embedder)


_build_lock = threading.Lock()


def get_retriever(persona: str, variant: str | None = None):
    """Process-wide retriever per persona. The lock stops parallel first searches from
    building (and writing) the same index at once."""
    with _build_lock:
        return _cached(persona, variant)


@cache
def _cached(persona: str, variant: str | None):
    return build_retriever(persona, variant)
