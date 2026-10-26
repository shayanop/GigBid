"""The explicit promotion policy for long-term memory. Nothing reaches the style store
except through observe_edit and nothing reaches the outcome store except through
record_outcome; raw tool output never does.

Style. Every human edit runs through deterministic detectors (no model, so every finding
is explainable). A finding is a candidate with its evidence; it becomes a preference once
`memory.style_min_support` separate edits show it. Opposite findings (shorter, longer)
retract each other. The same edit never counts twice, even if a node is retried.

Outcomes. Structured pipeline events (submitted, replied, interview) are counted per job
skill. They are stored as they happen but only shown to agents once a skill has
`memory.outcomes_min_samples` submissions.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from agent.config import load_config
from agent.memory.store import CANDIDATES, OUTCOMES, STYLE, ns

CITATION = re.compile(r"\s*\(?\[[\w./-]+#\d+\](?:\s*,\s*\[[\w./-]+#\d+\])*\)?")
OPPOSITE = {"shorter": "longer", "longer": "shorter"}
EVENTS = ("submitted", "replied", "interview")


@dataclass(frozen=True)
class Finding:
    key: str
    statement: str
    example: str


def _plain(text: str) -> str:
    return CITATION.sub("", text).strip()


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text).strip().lower()


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", _plain(text).split("\n")[0].strip())[0]


def detect(before: str, after: str) -> list[Finding]:
    """What one edit says about the freelancer's style."""
    findings = []
    opener = _first_sentence(before)
    if opener and _norm(opener) not in _norm(after):
        findings.append(Finding("drop_opener", "Open with the client's problem; skip greetings "
                                "and pleasantries.", f"Removed the opening: “{opener}”"))
    words_before, words_after = len(_plain(before).split()), len(_plain(after).split())
    if words_before and words_after <= 0.8 * words_before:
        findings.append(Finding("shorter", f"Keep it short, about {round(words_after, -1)} words.",
                                f"Cut from {words_before} to {words_after} words"))
    elif words_before and words_after >= 1.25 * words_before:
        findings.append(Finding("longer", f"Give more detail, about {round(words_after, -1)} words.",
                                f"Grew from {words_before} to {words_after} words"))
    closing = _plain(after).strip().split("\n")[-1].strip()
    if 0 < len(closing.split()) <= 8 and _norm(closing) not in _norm(before):
        findings.append(Finding(f"signoff:{_norm(closing).replace(' ', '-')[:40]}",
                                f"End with “{closing}”.", f"Added the closing “{closing}”"))
    return findings


async def observe_edit(store, user_id, before: str, after: str, source: str) -> list[str]:
    """Records the evidence in one edit; returns the keys promoted by it."""
    edit_id = hashlib.sha256(f"{before}\x00{after}".encode()).hexdigest()[:16]
    support = load_config()["memory"]["style_min_support"]
    promoted = []
    for finding in detect(before, after):
        if opposite := OPPOSITE.get(finding.key):  # contradicting evidence retracts
            await store.adelete(ns(user_id, CANDIDATES), opposite)
            await store.adelete(ns(user_id, STYLE), opposite)
        existing = await store.aget(ns(user_id, STYLE), finding.key)
        target = STYLE if existing else CANDIDATES
        item = existing or await store.aget(ns(user_id, CANDIDATES), finding.key)
        record = dict(item.value) if item else {"edits": [], "examples": [], "sources": []}
        if edit_id in record["edits"]:
            continue  # this edit was already counted
        record.update(statement=finding.statement, edits=[*record["edits"], edit_id],
                      examples=[*record["examples"], finding.example][-5:],
                      sources=[*record["sources"], source][-5:])
        if target == CANDIDATES and len(record["edits"]) >= support:
            target = STYLE
            record.update(promoted_at=datetime.now(UTC).isoformat(),
                          rule=f"Seen in {len(record['edits'])} separate edits "
                               f"(promotes at {support})")
            await store.adelete(ns(user_id, CANDIDATES), finding.key)
            promoted.append(finding.key)
        await store.aput(ns(user_id, target), finding.key, record)
    return promoted


async def record_outcome(store, user_id, skills: list[str], event: str, job_id: str) -> None:
    """Counts one pipeline event for each of the job's skills (idempotent per job)."""
    assert event in EVENTS
    for skill in skills:
        item = await store.aget(ns(user_id, OUTCOMES), skill.lower())
        record = dict(item.value) if item else {"skill": skill, **{e: [] for e in EVENTS}}
        if job_id not in record[event]:
            record[event] = [*record[event], job_id]
            await store.aput(ns(user_id, OUTCOMES), skill.lower(), record)
