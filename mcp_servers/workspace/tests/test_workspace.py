"""Workspace MCP tools over an in-memory MCP client, against a throwaway calendar."""

from datetime import datetime

import pytest
from mcp import Client

from mcp_servers.workspace import server


@pytest.fixture(autouse=True)
def calendar(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_LOCAL_USER", "fr_ml")
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))


async def call(tool: str, **args):
    async with Client(server.mcp) as client:
        return await client.call_tool(tool, args)


async def test_free_slots_are_weekday_one_per_day_and_avoid_busy_time():
    slots = (await call("find_free_slots", limit=3)).structured_content["result"]
    busy = server._load("fr_ml")["events"]
    days = [datetime.fromisoformat(s["start"]).date() for s in slots]
    assert len(slots) == 3 and len(set(days)) == 3
    assert all(datetime.fromisoformat(s["start"]).weekday() < 5 for s in slots)
    assert not any(server._overlaps(datetime.fromisoformat(s["start"]),
                                    datetime.fromisoformat(s["end"]), busy) for s in slots)


async def test_hold_is_idempotent_and_blocks_the_slot():
    slot = (await call("find_free_slots", limit=1)).structured_content["result"][0]
    args = {**slot, "title": "Interview: RAG chatbot", "idempotency_key": "hold-key-01"}
    first = (await call("hold_slot", **args)).structured_content
    again = (await call("hold_slot", **args)).structured_content
    assert first == again and first["status"] == "tentative"
    other = await call("hold_slot", **{**args, "idempotency_key": "hold-key-02"})
    assert other.is_error and "no longer free" in other.content[0].text
    assert (await call("find_free_slots", limit=1)).structured_content["result"][0] != slot


async def test_email_draft_is_saved_once():
    args = {"subject": "Interview prep", "body": "Notes", "idempotency_key": "mail-key-01"}
    assert (await call("create_email_draft", **args)).structured_content == \
        (await call("create_email_draft", **args)).structured_content
    assert len(server._load("fr_ml")["drafts"]) == 1
