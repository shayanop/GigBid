"""Shared node plumbing: versioned prompts, fencing of untrusted text, LLM calls
with token accounting, and the per-node budget and trace wrapper (C2, C4, E4)."""

import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache, wraps
from pathlib import Path
from typing import Any

from langgraph.runtime import get_runtime

from agent import config

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
_calls: ContextVar[list | None] = ContextVar("node_calls", default=None)


class ModelOutputError(Exception):
    """The model returned output that does not fit the schema; worth retrying."""


@dataclass
class Context:
    """Per-run dependencies passed as graph context (never checkpointed)."""
    toolbox: Any  # agent.mcp_client.Toolbox


def toolbox():
    return get_runtime(Context).context.toolbox


def record(event: dict) -> None:
    """Adds a tool or model call to the running node's trace entry."""
    if (calls := _calls.get()) is not None:
        calls.append(event)


@cache
def prompt(node: str) -> tuple[int, str]:
    """(version, system prompt) from agent/prompts/<node>.md front matter."""
    _, front, body = (PROMPTS / f"{node}.md").read_text(encoding="utf-8").split("---\n", 2)
    return int(re.search(r"version:\s*(\d+)", front).group(1)), body.strip()


def untrusted(tag: str, text: str) -> str:
    """Fences marketplace text so the model treats it as data; strips look-alike tags."""
    clean = re.sub(rf"</?\s*{tag}\b[^>]*>", "", text, flags=re.IGNORECASE)
    return f"<{tag}>\n{clean}\n</{tag}>"


def evidence_block(evidence) -> str:
    return "\n\n".join(
        f"[{e.id}] {e.type}, project {e.project}, date {e.date}, outcome {e.outcome}\n{e.text}"
        for e in evidence)


def job_block(job) -> str:
    """Trusted marketplace fields as plain text, free text fenced as untrusted."""
    budget = (f"{job.budget_type}, {job.budget_min or '?'}-{job.budget_max or '?'} USD"
              if job.budget_max else f"{job.budget_type}, not stated")
    questions = "\n".join(f"- {q}" for q in job.screening_questions) or "none"
    return (f"Job id: {job.id}\nBudget: {budget}\nListed skills: {', '.join(job.skills)}\n"
            + untrusted("job_post", f"{job.title}\n\n{job.description}\n\n"
                                    f"Screening questions:\n{questions}"))


def drop_sentences(text: str, sentences) -> str:
    for s in sentences:
        text = text.replace(s, "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


async def ask(node: str, schema, user: str):
    """Structured LLM call for `node`; records prompt version, tokens and latency."""
    version, system = prompt(node)
    start = time.perf_counter()
    out = await config.get_model(node, schema).ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": user}])
    usage = getattr(out["raw"], "usage_metadata", None) or {}
    record({"kind": "llm", "prompt_version": version, "tokens": usage.get("total_tokens", 0),
            "ms": round((time.perf_counter() - start) * 1000, 1)})
    if out["parsed"] is None:
        raise ModelOutputError(f"{node}: unparseable model output: {out.get('parsing_error')}")
    return out["parsed"]


def node(name: str):
    """Wraps a node: enforces the thread's step/token budget and appends a trace event."""
    def wrap(fn):
        @wraps(fn)
        async def run(state: dict) -> dict:
            budget, used = config.load_config()["budgets"], state.get("usage") or {}
            if (used.get("steps", 0) >= budget["max_steps"]
                    or used.get("tokens", 0) >= budget["max_tokens"]):
                return {"status": "needs_attention",
                        "attention": f"budget exhausted before {name}: {used}"}
            calls: list[dict] = []
            token = _calls.set(calls)
            start, at = time.perf_counter(), datetime.now(UTC).isoformat()
            try:
                update = await fn(state) or {}
            finally:
                _calls.reset(token)
            tokens = sum(c.get("tokens", 0) for c in calls)
            return {**update, "usage": {"steps": 1, "tokens": tokens},
                    "trace": [{"node": name, "at": at, "tokens": tokens, "calls": calls,
                               "ms": round((time.perf_counter() - start) * 1000, 1)}]}
        return run
    return wrap
