# Runbook

## Start the stack

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m apps.api.seed
```

Web app on :3000, API on :8000 (OpenAPI at `/docs`), GigSim :8100, Marketplace MCP :8200, Portfolio MCP :8300, Workspace MCP :8400. The demo account is `DEMO_EMAIL` / `DEMO_PASSWORD` from `.env`.

Local processes instead of containers (Postgres and Redis still from compose): `make gigsim`, `make marketplace-mcp`, `make portfolio-mcp`, `make api`, `make worker`, `make web`. Set `GIGBID_PROFILE=fake` to run every agent on the scripted model (no API key, no cost).

GigSim keeps its state in memory: restarting it (or rebuilding the shared Python image) resets Connects balances and proposals.

## Web client and end-to-end tests

The TypeScript client in `apps/web/src/lib/api` is generated; after any API change run `npm --prefix apps/web run gen:api` and commit the result (CI fails when it is stale).

`make e2e` starts its own GigSim, MCP servers, API, worker and a production web build on ports 3010–8310 against `TEST_DATABASE_URL` with the `fake` profile, so it can run next to the dev stack. The HTML report lands in `apps/web/playwright-report`.

## Polling policy (conservative by design)

| Rule | Where | Value |
| --- | --- | --- |
| Minimum saved-search interval | DB check constraint and API validation | 15 minutes |
| Scheduler tick | `worker/main.py` cron | every 5 minutes; only due searches run |
| Jobs taken on a search's first run | `scouting.first_run_limit` | 5 |
| Jobs taken per later run | `scouting.per_run_limit` | 10, only jobs posted since the last run |
| Concurrent graph runs | `worker.max_jobs` | 2 (Groq free tier rate-limits beyond this) |
| Marketplace calls per user | `MARKETPLACE_RATE_PER_MIN` | 60 per minute |
| Inbox check | every scheduler tick, or **Check for new messages** (at most once a minute per user) | one `list_messages` call per user |

Live Upwork mode uses the same limits; never lower the interval to approximate scraping.

### Model rate limits

Free-tier limits, read from the providers' `x-ratelimit-*` response headers on 2026-11-13:

| Bucket | Requests | Tokens |
| --- | --- | --- |
| Groq `gpt-oss-20b` | 1,000 a day | 8k a minute |
| Groq `gpt-oss-120b` | 1,000 a day | 8k a minute, separate from 20b |
| Cerebras `gpt-oss-120b` | 5 a minute, 150 an hour, 2,400 a day | 30k a minute, 1M a day |

One proposal takes about 10 model calls and 19–24k tokens. The verifier alone uses 38% of
the tokens, then the writer (18%), matcher (15%), critic (12%) and the small nodes.
On one 8k-a-minute Groq bucket, a single proposal overruns the minute.

`GIGBID_PROFILE=cerebras` gives each node group its own bucket:

| Bucket | Nodes |
| --- | --- |
| Cerebras | Verifier and matcher |
| Groq 120b | Writer, critic, liaison and judge |
| Groq 20b | The small nodes |

The critic ran on NIM until 2026-11-15, when NIM's free `gpt-oss-20b` took 70–106 s to
answer a five-word prompt.

Every fallback points at a different bucket. Cerebras calls are spaced 12 s apart in each
process (`agent/config._cerebras_pace`), so they wait instead of getting a 429.

Three bids in a row ran with 0 429s, at about 35 s each.

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

## Tracing (Phoenix)

[`agent/tracing.py`](../agent/tracing.py) exports OpenTelemetry spans to Arize Phoenix when
`PHOENIX_COLLECTOR_ENDPOINT` is set. Compose sets it to its own `phoenix` service; the UI is
at http://localhost:6006.

**What is traced.** Every LangGraph node and every model call in a worker run becomes a
span, with its prompt, output and token counts. The run's spans share one session id: the
GigBid trace id.

**Following one id.** The same trace id is returned on every API response as `X-Trace-Id`,
passed to the worker job, sent to every MCP server as `X-Trace-Id`, and written in the
marketplace audit log (`MARKETPLACE_AUDIT_LOG`). Search for it in Phoenix's Sessions view
or grep the audit log to follow one request end to end.

**PII.** String attributes pass through `agent.redact` before export, so emails and phone
numbers in job posts or client messages are masked in Phoenix too
(`tests/unit/test_tracing.py`).

**Public traces.** The README is meant to link three public traces, which needs a shared
Phoenix. Create a Phoenix Cloud space, then set `PHOENIX_COLLECTOR_ENDPOINT` to its
collector URL and `OTEL_EXPORTER_OTLP_HEADERS` to the auth header its setup page gives.
Run a bid that is approved, one skipped as a scam and one with a Critic loop, and share
those three traces. This needs the account owner.

Per-node tokens and model are also in each thread's own trace (the run timeline in the
web app, `trace` in the graph state). `evals/runners/budget_eval.py` prices them.
