"""MCP access for graph nodes (A6): per-agent tool allowlists, timeouts and bounded
retries. A target is a URL (deployed, bearer token per server) or an in-process
MCPServer (tests, single-process dev)."""

import asyncio
import time
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from agent.nodes.common import record

ALLOWLIST: dict[str, set[tuple[str, str]]] = {
    "scout": {("marketplace", "get_job"), ("marketplace", "search_jobs")},
    "risk": {("marketplace", "get_client_history")},
    "matcher": {("portfolio", "search_evidence")},
    "pricing": {("marketplace", "search_jobs")},
    "writer": {("portfolio", "search_evidence"), ("portfolio", "get_case_study")},
    "critic": {("portfolio", "search_evidence")},
    "approval": {("marketplace", "create_proposal_draft")},  # dry_run previews only
    "submit": {("marketplace", "create_proposal_draft"), ("marketplace", "submit_proposal")},
}


class ToolCallError(Exception):
    """The tool refused the call (bad input, not found, insufficient Connects...)."""


class ToolUnavailable(ToolCallError):
    """The server behind the tool is down after retries; the work can be re-queued."""


class Toolbox:
    def __init__(self, targets: dict[str, Any], tokens: dict[str, str] | None = None,
                 trace_id: str | None = None, timeout: float = 30, attempts: int = 3,
                 backoff: float = 0.5):
        self.targets, self.tokens, self.trace_id = targets, tokens or {}, trace_id
        self.timeout, self.attempts, self.backoff = timeout, attempts, backoff

    def _client(self, server: str) -> Client:
        target = self.targets[server]
        if not isinstance(target, str):
            return Client(target)
        headers = {"Authorization": f"Bearer {self.tokens[server]}"}
        if self.trace_id:
            headers["X-Trace-Id"] = self.trace_id
        return Client(streamable_http_client(target, http_client=httpx2.AsyncClient(
            headers=headers, timeout=self.timeout)))

    async def call(self, agent: str, server: str, tool: str, args: dict) -> Any:
        if (server, tool) not in ALLOWLIST.get(agent, set()):
            raise PermissionError(f"{agent} may not call {server}.{tool}")
        start = time.perf_counter()
        for attempt in range(self.attempts):
            last = attempt == self.attempts - 1
            try:
                async with asyncio.timeout(self.timeout), self._client(server) as client:
                    result = await client.call_tool(tool, args)
            except (TimeoutError, OSError, httpx2.TransportError):
                if last:
                    raise
            else:
                message = result.content[0].text if result.is_error and result.content else ""
                if not result.is_error or "unavailable" not in message or last:
                    break
            await asyncio.sleep(min(self.backoff * 2**attempt, 4))
        record({"kind": "tool", "tool": f"{server}.{tool}", "ok": not result.is_error,
                "ms": round((time.perf_counter() - start) * 1000, 1)})
        if result.is_error:
            error = ToolUnavailable if "unavailable" in message else ToolCallError
            raise error(f"{server}.{tool}: {message}")
        data = result.structured_content
        return data["result"] if isinstance(data, dict) and data.keys() == {"result"} else data
