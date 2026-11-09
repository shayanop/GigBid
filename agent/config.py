"""Loads agent/config.yaml and builds the chat model for each graph node."""

import os
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

CONFIG_PATH = Path(__file__).with_name("config.yaml")

LLM_NODES = {"analyst", "risk", "matcher", "pricing", "writer", "verifier", "critic",
             "compliance", "intent", "liaison", "judge", "portfolio_builder"}


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
        spec = profile["nodes"][node]  # "provider:model" or [primary, fallback]
        return (spec, None) if isinstance(spec, str) else tuple(spec)
    return profile["default"], profile.get("default_fallback")


def groq_keys() -> list[str]:
    """GROQ_API_KEYS (comma-separated) or the single GROQ_API_KEY."""
    keys = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or ""
    return [k.strip() for k in keys.split(",") if k.strip()]


def _structured(llm, schema):
    # json_schema = constrained decoding; tool calling truncated long outputs on Groq gpt-oss.
    return llm.with_structured_output(schema, method="json_schema", include_raw=True) \
        if schema else llm


def _nvidia(model: str, schema, think: bool):
    """NVIDIA NIM (OpenAI-compatible). ChatNVIDIA's own structured output cannot return the
    raw message (token usage), so bind the json_schema response format and parse here."""
    from langchain_core.runnables import RunnableLambda
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    from pydantic import ValidationError
    # A short request timeout so a slow NIM call reaches the Groq backup quickly.
    llm = ChatNVIDIA(model=model, api_key=os.environ["NIM_API_KEY"].strip(), timeout=20,
                     max_completion_tokens=8192, temperature=0)
    if not think:  # hidden reasoning made extraction calls ~4x slower for the same labels
        llm = llm.bind(chat_template_kwargs={"enable_thinking": False})
    if not schema:
        return llm

    def parse(msg):
        try:
            return {"raw": msg, "parsed": schema.model_validate_json(msg.content),
                    "parsing_error": None}
        except ValidationError as e:
            return {"raw": msg, "parsed": None, "parsing_error": e}
    return llm.bind(response_format={"type": "json_schema", "json_schema": {
        "name": schema.__name__, "schema": schema.model_json_schema(), "strict": True}}) \
        | RunnableLambda(parse)


def _build(spec: str, schema, node: str):
    provider, model = spec.split(":", 1)
    if provider == "fake":
        from agent.fake_llm import scripted_model
        return scripted_model(node)
    if provider == "nvidia":
        return _nvidia(model, schema, node in active_profile().get("thinking", []))
    keys = groq_keys() if provider == "groq" else []
    if len(keys) < 2:
        return _structured(init_chat_model(model, model_provider=provider), schema)
    from groq import RateLimitError
    # One client per key: a 429 (per-minute or daily cap) shifts to the next key at once
    # instead of waiting it out; only the last key keeps the client's own retries.
    # ponytail: an exhausted key is still tried first on every call (one fast 429);
    # remember dead keys until their reset if that latency adds up.
    chain = [_structured(init_chat_model(model, model_provider=provider, api_key=key,
                                         max_retries=2 if i == len(keys) - 1 else 0), schema)
             for i, key in enumerate(keys)]
    return chain[0].with_fallbacks(chain[1:], exceptions_to_handle=(RateLimitError,))


def get_model(node: str, schema=None):
    """Chat model for `node`. With a Pydantic schema it returns
    {"raw": AIMessage, "parsed": schema | None, "parsing_error": ...} so callers keep
    token usage."""
    primary, fallback = model_spec(node)
    llm = _build(primary, schema, node)
    return llm.with_fallbacks([_build(fallback, schema, node)]) if fallback else llm
