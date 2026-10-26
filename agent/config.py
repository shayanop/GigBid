"""Loads agent/config.yaml and builds the chat model for each graph node."""

import os
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

CONFIG_PATH = Path(__file__).with_name("config.yaml")

LLM_NODES = {"analyst", "risk", "matcher", "pricing", "writer", "verifier", "critic",
             "compliance", "liaison"}


@cache
def load_config() -> dict:
    load_dotenv()
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def active_profile() -> dict:
    cfg = load_config()
    return cfg["profiles"][os.getenv("GIGBID_PROFILE", cfg["profile"])]


def model_spec(node: str) -> tuple[str, str | None]:
    """Returns (primary, fallback) "provider:model" specs for a node."""
    if node not in LLM_NODES:
        raise KeyError(f"unknown LLM node: {node}")
    profile = active_profile()
    if node in profile.get("nodes", {}):
        return profile["nodes"][node], None
    return profile["default"], profile.get("default_fallback")


def _build(spec: str, schema):
    provider, model = spec.split(":", 1)
    llm = init_chat_model(model, model_provider=provider)
    # json_schema = constrained decoding; tool calling truncated long outputs on Groq gpt-oss.
    return llm.with_structured_output(schema, method="json_schema", include_raw=True) \
        if schema else llm


def get_model(node: str, schema=None):
    """Chat model for `node`. With a Pydantic schema it returns
    {"raw": AIMessage, "parsed": schema | None, "parsing_error": ...} so callers keep
    token usage."""
    primary, fallback = model_spec(node)
    llm = _build(primary, schema)
    return llm.with_fallbacks([_build(fallback, schema)]) if fallback else llm
