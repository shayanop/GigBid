"""Retriever factory: picks the variant named in agent/config.yaml (rag.variant).

Every variant shares the V0 index. "v0" is plain dense search; v1 to v8 are presets in
rag/variants; "selected" uses rag.components from the config (the deployed pipeline);
"custom:hybrid+rerank" names any combination, for ablations. All return an object with
search(query, k, where) -> list[Evidence].
"""

import importlib
import threading
from functools import cache
from pathlib import Path

from agent.config import load_config

ROOT = Path(__file__).resolve().parents[1]
PERSONAS_DIR = ROOT / "data" / "personas"
INDEX_DIR = ROOT / "data" / "processed" / "index"
VARIANTS = {"v1": "v1_decompose", "v2": "v2_hybrid", "v3": "v3_rerank", "v4": "v4_outcome",
            "v8": "v8_corrective"}


def rag_config() -> dict:
    return load_config()["rag"]


def components_for(name: str):
    from rag.pipeline import Components
    if name == "v0":
        return Components()
    if name == "selected":
        return Components(**rag_config()["components"])
    if name.startswith("custom:"):
        return Components(**{flag: True for flag in name.removeprefix("custom:").split("+") if flag})
    return importlib.import_module(f"rag.variants.{VARIANTS[name]}").COMPONENTS


def build_retriever(persona: str, variant: str | None = None, embedder=None, grader=None):
    """Builds (incrementally) and returns the retriever; call again after uploads."""
    from rag.pipeline import Pipeline, cross_encoder
    from rag.variants import v0_naive
    cfg = rag_config()
    components = components_for(variant or cfg["variant"])
    index = v0_naive.build(persona, embedder)
    if not components.on():
        return index
    if grader is None and (components.rerank or components.corrective):
        grader = cross_encoder(cfg["reranker"])
    return Pipeline(index, components, grader, cfg["grade_threshold"])


_build_lock = threading.Lock()


def get_retriever(persona: str, variant: str | None = None):
    """Process-wide retriever per persona. The lock stops parallel first searches from
    building (and writing) the same index at once."""
    with _build_lock:
        return _cached(persona, variant)


@cache
def _cached(persona: str, variant: str | None):
    return build_retriever(persona, variant)


def warm_all() -> list[str]:
    """Builds (or refreshes) every persona's index up front. The first build downloads the
    embedding model and embeds the whole portfolio, which takes longer than an agent's
    tool-call timeout, so servers do it before taking requests."""
    personas = sorted(p.name for p in PERSONAS_DIR.iterdir() if (p / "case_studies").is_dir())
    for persona in personas:
        get_retriever(persona)
    return personas
