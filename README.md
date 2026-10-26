# GigBid

A freelancer's copilot built from a team of LangGraph agents. GigBid finds freelance jobs, judges whether they are worth a bid, drafts proposals where every claim is backed by your own portfolio, and handles client conversations. **Nothing is ever sent without your approval.**

It runs against **GigSim**, a marketplace simulator, for safe development; the same interface is meant for Upwork's official MCP server in live mode.

## How it works

- **Bid graph** (one thread per job): Scout loads the job; Job Analyst, Risk Assessor and Fit Matcher run in parallel; a decision step bids, watches or skips; then Pricing, Proposal Writer, Claim Verifier, Critic (at most 2 rewrites) and Compliance Guard; then it pauses for your approval before anything is submitted. Diagram: [docs/images/bid_graph.mmd](docs/images/bid_graph.mmd)
- **Conversation graph** (one thread per client conversation): the Client Liaison classifies the client's message, offers interview times from your calendar, drafts a reply, checks it and waits for your approval. Diagram: [docs/images/conversation_graph.mmd](docs/images/conversation_graph.mmd)
- **MCP tool layer**: agents only reach the marketplace, your portfolio and your calendar through MCP servers ([docs/TOOLS.md](docs/TOOLS.md)).
- **Evidence search**: your CV, case studies, code, reviews and past proposals are indexed for retrieval.
- **Memory**: preferences learned from your edits (after 2 matching edits) and outcomes per skill, both visible and deletable in Settings.
- **Web app** (Next.js) over a FastAPI API; a worker runs every graph and scheduled search.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- Node.js 24 and npm
- Docker Desktop (Postgres and Redis, or the whole stack)
- A [Groq](https://console.groq.com) API key, or use the free scripted `fake` model profile (see [Configuration](#configuration))

`make` is optional. Every target below also shows the plain command, which is what to use on Windows without make.

## 1. Set up

```bash
git clone https://github.com/shayanop/GigBid.git
cd GigBid
uv sync
npm --prefix apps/web ci
cp .env.example .env
```

Fill in `.env`. Generate each secret (`POSTGRES_PASSWORD`, `SESSION_SECRET`, `MCP_SIGNING_SECRET`, `DEMO_PASSWORD`) with:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then put the same Postgres password into `DATABASE_URL` and `TEST_DATABASE_URL`, and add `GROQ_API_KEY`.

## 2. Run everything with Docker

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

Create the demo account (email and password come from `DEMO_EMAIL` / `DEMO_PASSWORD` in `.env`):

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m apps.api.seed
```

Open http://localhost:3000 and sign in.

| Service | URL |
| --- | --- |
| Web app | http://localhost:3000 |
| API (OpenAPI docs at `/docs`) | http://localhost:8000 |
| GigSim marketplace simulator | http://localhost:8100 |
| Marketplace / Portfolio / Workspace MCP | http://localhost:8200/mcp, :8300/mcp, :8400/mcp |
| Phoenix tracing UI | http://localhost:6006 |
| Postgres, Redis, Ollama | 5432, 6379, 11434 |

The Ollama and Phoenix images are large. To start only what the app needs:

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build web api worker gigsim marketplace-mcp portfolio-mcp workspace-mcp postgres redis
```

Stop the stack (add `-v` to also delete the data volumes):

```bash
docker compose -f infra/docker-compose.yml --env-file .env down
```

Rebuild after code changes:

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d --build api worker web
```

## 3. Run as local processes (for development)

Start only Postgres and Redis in Docker:

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d postgres redis
```

Then run each process in its own terminal:

| make | Plain command | Port |
| --- | --- | --- |
| `make gigsim` | `uv run uvicorn gigsim.app:create_app --factory --port 8100` | 8100 |
| `make marketplace-mcp` | `uv run python -m mcp_servers.marketplace.server` | 8200 |
| `make portfolio-mcp` | `uv run python -m mcp_servers.portfolio.server` | 8300 |
| `make workspace-mcp` | `uv run python -m mcp_servers.workspace.server` | 8400 |
| `make api` | `uv run uvicorn apps.api.main:create_app --factory --port 8000 --loop asyncio:SelectorEventLoop` | 8000 |
| `make worker` | `uv run python -m worker.main` | none |
| `make web` | `npm --prefix apps/web run dev` | 3000 |
| `make seed` | `uv run python -m apps.api.seed` | creates the demo account |

The Portfolio server builds every persona's search index before it starts listening, so its first start takes a minute (it also downloads the embedding model once).

The `--loop asyncio:SelectorEventLoop` flag on the API matters on Windows: the async Postgres driver cannot run on Windows' default event loop.

## 4. Try the agents from the command line

Runs the whole bid graph for one GigSim job with real models, with GigSim and the MCP servers inside the same process, and prints the decision, risk, fit, price, claims and draft. It stops at the approval step.

```bash
uv run python -m agent.graphs.bid_graph job_00012
```

(`make run-job JOB=job_00012` does the same.)

## 5. Tests

Unit, contract and integration tests (no API key needed; the agents use a scripted model):

```bash
uv run pytest -m "not live"
```

The integration tests for the API and worker also need Postgres and Redis running and `TEST_DATABASE_URL` / `TEST_REDIS_URL` in `.env`; without them those tests are skipped. Create the test database once:

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec postgres psql -U gigbid -d gigbid -c "CREATE DATABASE gigbid_test"
```

Live test against Groq (needs `GROQ_API_KEY`):

```bash
uv run pytest -m live
```

End-to-end browser tests (Playwright). They start their own GigSim, MCP servers, API, worker and a production web build on ports 3010 to 8410, against the test database, so they can run next to the dev stack. Install the browser once:

```bash
npm --prefix apps/web exec -- playwright install chromium
```

Then run them (Postgres and Redis must be running):

```bash
npm --prefix apps/web run test:e2e
```

The HTML report is written to `apps/web/playwright-report`.

Lint and type checks:

```bash
uv run ruff check .
```

```bash
npm --prefix apps/web run lint
```

Refresh the MCP tool schema snapshots after an intentional tool change (CI fails on unplanned changes):

```bash
UPDATE_SNAPSHOTS=1 uv run pytest tests/contract
```

## 6. Data and evaluation

Regenerate the synthetic persona portfolios and the dev retrieval labels (deterministic):

```bash
uv run python -m data.personas.generate
```

Run the retrieval evaluation (Recall@5, MRR, nDCG@10; results in `evals/results/`):

```bash
uv run python -m evals.runners.rag_eval --variant v0
```

Add `--limit 20` for a quick smoke run. Regenerate the graph diagrams with `make diagram`.

## 7. Generated API client

The TypeScript client in `apps/web/src/lib/api` is generated from the API's OpenAPI document. After changing the API, regenerate it and commit the result (CI fails if it is stale):

```bash
npm --prefix apps/web run gen:api
```

## 8. Use the MCP servers from other hosts

The Portfolio server works over stdio in hosts such as Claude Desktop or Cursor:

```json
{"mcpServers": {"gigbid-portfolio": {"command": "uv", "args": ["--directory", "<path to GigBid>", "run",
  "python", "-m", "mcp_servers.portfolio.server", "--stdio"], "env": {"PORTFOLIO_LOCAL_USER": "fr_ml"}}}}
```

To call any server over HTTP, mint a bearer token for an account (valid 30 days):

```bash
uv run python -m mcp_servers.auth fr_ml --days 30
```

Rotating `MCP_SIGNING_SECRET` revokes every token.

## Configuration

Everything an agent decides from (models, thresholds, budgets, fees, polling limits, memory rules) lives in [agent/config.yaml](agent/config.yaml), not in code.

Model profiles, chosen with `GIGBID_PROFILE` in `.env`:

| Profile | Models |
| --- | --- |
| `open` (default) | Groq: `gpt-oss-20b` for most agents, `gpt-oss-120b` for Writer, Critic and Client Liaison |
| `open_alt` | Groq: `gpt-oss-20b` everywhere (the cheaper configuration to compare against) |
| `local` | Ollama `qwen3:4b` for most agents (pull it with `make models`), Groq for the drafting agents |
| `fake` | Scripted, deterministic answers: no API key, no cost; used by the end-to-end tests |

GigSim test accounts: `fr_ml` (AI/ML engineer), `fr_fs` (full-stack developer), `fr_da` (data analyst).

## Troubleshooting

- **`make` not found on Windows**: use the plain commands in the tables above.
- **API fails at startup on Windows with an event-loop error**: start it with `--loop asyncio:SelectorEventLoop` (as `make api` does).
- **Connects balance reset, proposals gone**: GigSim keeps its state in memory; restarting it, or rebuilding the shared Python image, resets it.
- **Groq 429 "rate limit" errors**: the free tier is easily exhausted. Runs that hit it end as "needs attention" and are replayed automatically later; `worker.max_jobs` in the config keeps concurrency at 2.
- **E2E run says `TEST_DATABASE_URL is not set`**: add it to `.env` and create the test database (section 5).
- **Recovery and polling rules**: see [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Project layout

```text
agent/          graphs, agent nodes, prompts, handoff models, memory, model config
apps/api/       FastAPI: auth, jobs, approvals, messages, runs (SSE), memory
apps/web/       Next.js app, generated API client, Playwright tests
worker/         Arq worker: graph runs, scheduled scouting, inbox checks, recovery
mcp_servers/    marketplace, portfolio and workspace MCP servers
rag/            portfolio ingestion, index and retrieval variants
gigsim/         marketplace simulator with synthetic jobs, clients and replies
data/           synthetic persona portfolios and the marketplace policy pack
evals/          evaluation datasets, runners and results
infra/          Dockerfiles and docker-compose.yml
docs/           tools, data card, runbook, graph diagrams
```

The full project specification is in [GigBid_Project_Specification.md](GigBid_Project_Specification.md).
