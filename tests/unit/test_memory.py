import asyncio

from langgraph.store.memory import InMemoryStore

from agent.memory import promotion_rules as rules
from agent.memory import store as memory

GENERIC = ("I hope this message finds you well. Your team needs a RAG pipeline [p1#0]. "
           "I built one for a fintech client and it cut response time in half [p1#0]. "
           "I would start with a short call to agree scope, data access and milestones. "
           "Then I would ship a first version within a week.")


def test_detectors_explain_what_an_edit_shows():
    after = "Your team needs a RAG pipeline. I built one for a fintech client.\nBest, Sana"
    keys = {f.key for f in rules.detect(GENERIC, after)}
    assert keys == {"drop_opener", "shorter", "signoff:best-sana"}
    assert rules.detect(GENERIC, GENERIC) == []


def test_a_preference_needs_two_separate_edits_and_counts_each_edit_once():
    async def go():
        store, user = InMemoryStore(), "u1"
        edit = GENERIC.replace("I hope this message finds you well. ", "")
        assert await rules.observe_edit(store, user, GENERIC, edit, "proposal:a") == []
        assert await rules.observe_edit(store, user, GENERIC, edit, "proposal:a") == []  # retry
        assert await memory.style_preferences(store, user) == []  # candidates stay private
        other = GENERIC.replace("I hope this message finds you well.", "Hi there!")
        second = other.replace("Hi there! ", "")
        assert await rules.observe_edit(store, user, other, second, "message:b") == ["drop_opener"]
        prefs = await memory.everything(store, user)
        assert [p["key"] for p in prefs["preferences"]] == ["drop_opener"]
        assert prefs["preferences"][0]["sources"] == ["proposal:a", "message:b"]
        assert "2 separate edits" in prefs["preferences"][0]["rule"]

        await memory.forget(store, user, memory.STYLE, "drop_opener")  # evidence goes too
        assert await rules.observe_edit(store, user, GENERIC, edit + " ", "proposal:c") == []
        assert await memory.style_preferences(store, user) == []
    asyncio.run(go())


def test_opposite_findings_retract_each_other():
    async def go():
        store = InMemoryStore()
        await rules.observe_edit(store, "u", GENERIC, GENERIC[:120], "a")
        assert (await memory.everything(store, "u"))["learning"][0]["key"] in {"shorter", "drop_opener"}
        await rules.observe_edit(store, "u", GENERIC, GENERIC + " " + GENERIC, "b")
        keys = {i["key"] for i in (await memory.everything(store, "u"))["learning"]}
        assert "shorter" not in keys and "longer" in keys
    asyncio.run(go())


def test_outcome_rates_are_shown_only_with_enough_samples(monkeypatch):
    from agent.config import load_config
    monkeypatch.setitem(load_config()["memory"], "outcomes_min_samples", 3)

    async def go():
        store = InMemoryStore()
        for job in ("j1", "j2"):
            await rules.record_outcome(store, "u", ["LangGraph", "RAG"], "submitted", job)
        assert await memory.outcome_notes(store, "u", ["LangGraph"]) == []
        await rules.record_outcome(store, "u", ["LangGraph"], "submitted", "j3")
        await rules.record_outcome(store, "u", ["LangGraph"], "interview", "j1")
        await rules.record_outcome(store, "u", ["LangGraph"], "interview", "j1")  # once
        assert await memory.outcome_notes(store, "u", ["LangGraph", "RAG"]) == [
            "LangGraph jobs: 1 of 3 proposals got a reply (33%), 1 led to an interview"]
    asyncio.run(go())
