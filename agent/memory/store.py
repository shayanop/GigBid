"""Long-term memory (C2, R7), the third layer next to graph state and the execution trace.

Namespaces per user, in a LangGraph store (Postgres in deployment):
- ("users", id, "style"): promoted writing preferences. The only style memory agents read.
- ("users", id, "style_candidates"): findings still gathering evidence.
- ("users", id, "outcomes"): proposal outcomes counted per skill.
Only agent/memory/promotion_rules.py writes here.
"""

import os
from contextlib import asynccontextmanager

from langgraph.store.postgres.aio import AsyncPostgresStore

from agent.config import load_config
from agent.graphs.checkpoint import migration_lock

STYLE, CANDIDATES, OUTCOMES = "style", "style_candidates", "outcomes"


def ns(user_id, kind: str) -> tuple[str, ...]:
    return ("users", str(user_id), kind)


@asynccontextmanager
async def postgres_store(url: str | None = None):
    async with AsyncPostgresStore.from_conn_string(url or os.environ["DATABASE_URL"]) as store:
        async with migration_lock(url):
            await store.setup()
        yield store


async def _all(store, user_id, kind: str) -> list[dict]:
    items = await store.asearch(ns(user_id, kind), limit=200)
    return [{"key": i.key, **i.value} for i in items]


async def style_preferences(store, user_id) -> list[str]:
    """Promoted preferences only; candidates never reach a prompt."""
    return [p["statement"] for p in await _all(store, user_id, STYLE)]


def outcome_rate(record: dict) -> tuple[int, int, int]:
    """(submitted, replied or interviewed, interviewed) for one skill."""
    submitted = set(record["submitted"])
    answered = (set(record["replied"]) | set(record["interview"])) & submitted
    return len(submitted), len(answered), len(set(record["interview"]) & submitted)


async def outcome_notes(store, user_id, skills: list[str]) -> list[str]:
    """Reply rates for these skills, only where there are enough submissions to mean
    something (memory.outcomes_min_samples)."""
    minimum, notes = load_config()["memory"]["outcomes_min_samples"], []
    for skill in skills:
        item = await store.aget(ns(user_id, OUTCOMES), skill.lower())
        if not item:
            continue
        sent, answered, interviews = outcome_rate(item.value)
        if sent >= minimum:
            notes.append(f"{item.value['skill']} jobs: {answered} of {sent} proposals got a reply "
                         f"({answered / sent:.0%}), {interviews} led to an interview")
    return notes


async def everything(store, user_id) -> dict:
    return {"preferences": await _all(store, user_id, STYLE),
            "learning": await _all(store, user_id, CANDIDATES),
            "outcomes": await _all(store, user_id, OUTCOMES)}


async def forget(store, user_id, kind: str, key: str) -> None:
    """Deleting a preference deletes its evidence too, so it has to be earned again."""
    if kind == STYLE:
        await store.adelete(ns(user_id, CANDIDATES), key)
    await store.adelete(ns(user_id, kind), key)
