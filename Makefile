.PHONY: dev gigsim marketplace-mcp portfolio-mcp workspace-mcp data seed api worker diagram run-job eval models test test-live lint e2e web

COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

dev:
	$(COMPOSE) up -d

gigsim:
	uv run uvicorn gigsim.app:create_app --factory --port 8100

marketplace-mcp:
	uv run python -m mcp_servers.marketplace.server

portfolio-mcp:
	uv run python -m mcp_servers.portfolio.server

workspace-mcp:
	uv run python -m mcp_servers.workspace.server

data: # regenerate the synthetic personas and dev labels
	uv run python -m data.personas.generate

seed: # demo account and saved search
	uv run python -m apps.api.seed

api: # selector loop: psycopg async cannot run on Windows' default Proactor loop
	uv run uvicorn apps.api.main:app --port 8000 --loop asyncio:SelectorEventLoop

worker:
	uv run python -m worker.main

diagram:
	uv run python -c "from agent.graphs.bid_graph import build; print(build().get_graph().draw_mermaid())" > docs/images/bid_graph.mmd
	uv run python -c "from agent.graphs.conversation_graph import build; print(build().get_graph().draw_mermaid())" > docs/images/conversation_graph.mmd

run-job: # make run-job JOB=job_00012 (needs GROQ_API_KEY and make gigsim running)
	uv run python -m agent.graphs.bid_graph $(JOB)

eval:
	uv run python -m evals.runners.rag_eval --variant v0

models:
	$(COMPOSE) exec ollama ollama pull qwen3:4b

test:
	uv run pytest -m "not live"

test-live:
	uv run pytest -m live

lint:
	uv run ruff check .
	npm --prefix apps/web run lint

e2e: # needs Postgres and Redis running
	npm --prefix apps/web run test:e2e

web:
	npm --prefix apps/web run dev
