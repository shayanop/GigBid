"""Fails when an MCP server's tools, resource templates or prompts change without
updating the snapshot. Regenerate deliberately: UPDATE_SNAPSHOTS=1 uv run pytest tests/contract"""

import json
import os
from pathlib import Path

import pytest
from mcp import Client

from mcp_servers.marketplace import server as marketplace
from mcp_servers.portfolio import server as portfolio

SNAPSHOTS = Path(__file__).with_name("snapshots")


def _dump(items) -> dict:
    return {i.name: i.model_dump(mode="json", by_alias=True, exclude_none=True) for i in items}


@pytest.mark.parametrize("name,mcp_server", [("marketplace", marketplace.mcp),
                                             ("portfolio", portfolio.mcp)])
async def test_mcp_interface_matches_snapshot(name, mcp_server):
    async with Client(mcp_server) as client:
        current = {"tools": _dump((await client.list_tools()).tools),
                   "resource_templates": _dump(
                       (await client.list_resource_templates()).resource_templates),
                   "prompts": _dump((await client.list_prompts()).prompts)}
    path = SNAPSHOTS / f"{name}.json"
    if os.getenv("UPDATE_SNAPSHOTS"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert current == json.loads(path.read_text(encoding="utf-8"))
