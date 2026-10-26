# Runbook

## Start the stack

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m apps.api.seed
```

API on :8000 (OpenAPI at `/docs`), GigSim :8100, Marketplace MCP :8200, Portfolio MCP :8300. The demo account is `DEMO_EMAIL` / `DEMO_PASSWORD` from `.env`.

Local processes instead of containers (Postgres and Redis still from compose): `make gigsim`, `make marketplace-mcp`, `make portfolio-mcp`, `make api`, `make worker`.

## Polling policy (conservative by design)

| Rule | Where | Value |
| --- | --- | --- |
| Minimum saved-search interval | DB check constraint and API validation | 15 minutes |
| Scheduler tick | `worker/main.py` cron | every 5 minutes; only due searches run |
| Jobs taken on a search's first run | `scouting.first_run_limit` | 5 |
| Jobs taken per later run | `scouting.per_run_limit` | 10, only jobs posted since the last run |
| Concurrent graph runs | `worker.max_jobs` | 2 (Groq free tier rate-limits beyond this) |
| Marketplace calls per user | `MARKETPLACE_RATE_PER_MIN` | 60 per minute |

Live Upwork mode uses the same limits; never lower the interval to approximate scraping.

## How work is recovered

| Failure | What happens |
| --- | --- |
| Worker dies mid-run | Arq retries the job; the run continues from the last graph checkpoint. |
| Queue entry lost (Redis flush, crash between insert and enqueue) | Every tick re-queues threads stuck in `queued`, `analyzing` or `processing` for `worker.orphan_after_minutes`. |
| Worker dies after the human approved | The decision is stored on the thread (`pending_resume`) before it is queued, so the next run applies it. If the graph already consumed it, the run only refreshes the summary. |
| Duplicate delivery of any job | One run per thread at a time (Redis lock); runs decide from durable state; marketplace writes use idempotency keys. |
| Marketplace down, model rate limit, timeout | The thread ends as `needs_attention`, then is replayed from the checkpoint before the failure, up to `worker.max_replays` times, `worker.replay_delay_minutes` apart. |
| Any other node failure | `needs_attention` with the node and error in `attention`; shown in the inbox. |

Inspect a thread: `GET /runs/{thread_id}` (node trace with tool calls, tokens, timings) and the Marketplace audit log (`/audit/marketplace.jsonl` in the `marketplace-mcp` container), both keyed by trace id.

## Tokens for external MCP hosts

```bash
uv run python -m mcp_servers.auth fr_ml --days 30
```

Rotating `MCP_SIGNING_SECRET` revokes every token at once.
