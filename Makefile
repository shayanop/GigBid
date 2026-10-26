COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

dev:
	$(COMPOSE) up -d

gigsim:
	uv run uvicorn gigsim.app:create_app --factory --port 8100

marketplace-mcp:
	uv run python -m mcp_servers.marketplace.server

portfolio-mcp:
	uv run python -m mcp_servers.portfolio.server

seed:
	uv run python -m data.personas.generate

diagram:
	uv run python -c "from agent.graphs.bid_graph import build; print(build().get_graph().draw_mermaid())" > docs/images/bid_graph.mmd

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
