"""Fails when an MCP tool's name, schema or annotations change without updating the
snapshot. Regenerate deliberately with: UPDATE_SNAPSHOTS=1 uv run pytest tests/contract"""

import json
import os
from pathlib import Path

import pytest
from mcp import Client

from mcp_servers.marketplace import server as marketplace

SNAPSHOTS = Path(__file__).with_name("snapshots")


@pytest.mark.parametrize("name,mcp_server", [("marketplace", marketplace.mcp)])
async def test_tool_schemas_match_snapshot(name, mcp_server):
    async with Client(mcp_server) as client:
        tools = (await client.list_tools()).tools
    current = {t.name: t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools}
    path = SNAPSHOTS / f"{name}.json"
    if os.getenv("UPDATE_SNAPSHOTS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert current == json.loads(path.read_text(encoding="utf-8"))
