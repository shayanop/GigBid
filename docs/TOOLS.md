# Tools

One row per MCP tool. Schemas are snapshotted in `tests/contract/snapshots/`; any change fails CI until the snapshot is regenerated on purpose.

## Marketplace MCP (`mcp_servers/marketplace`, owned by GigBid)

Transport: Streamable HTTP at `/mcp`. Auth: bearer token mapped to a user (`MARKETPLACE_MCP_TOKENS`); in-process/stdio use `MARKETPLACE_LOCAL_USER`. Every call is rate limited per user (`MARKETPLACE_RATE_PER_MIN`, default 60) and appended to the audit log with user, tool, redacted arguments, redacted result and trace ID (`X-Trace-Id` header, generated if absent). The adapter (GigSim now, Upwork later) comes from `marketplace.adapter` in `agent/config.yaml`.

| Tool | Permission | Annotations | Notes |
| --- | --- | --- | --- |
| `search_jobs` | read | readOnly, openWorld | keywords (all must match), skills (any), `posted_after`, `limit` ≤ 50 |
| `get_job` | read | readOnly, openWorld | full description and screening questions |
| `get_client_history` | read | readOnly, openWorld | spend, hire rate, rating, reviews, payment verified |
| `get_connects_balance` | read | readOnly, openWorld | |
| `list_messages` | read | readOnly, openWorld | all threads with messages |
| `create_proposal_draft` | write | idempotent, non-destructive, openWorld | needs `idempotency_key`; `dry_run` previews payload and Connects cost; spends nothing |
| `submit_proposal` | write | idempotent, **destructive**, openWorld | spends Connects; needs `idempotency_key`; `dry_run` previews cost and balance after |
| `send_message` | write | idempotent, non-destructive, openWorld | needs `idempotency_key`; `dry_run` previews |

Write tools are only called after human approval in GigBid (LangGraph interrupt). The server itself does not decide approval.

## Third-party servers

Added with Phase 11 (official Upwork MCP, GitHub MCP), each with a trust rationale.
