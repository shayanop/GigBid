COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

dev:
	$(COMPOSE) up -d

gigsim:
	uv run uvicorn gigsim.app:create_app --factory --port 8100

marketplace-mcp:
	uv run python -m mcp_servers.marketplace.server

models:
	$(COMPOSE) exec ollama ollama pull qwen3:4b

test:
	uv run pytest -m "not live"

test-live:
	uv run pytest -m live

lint:
	uv run ruff check .
