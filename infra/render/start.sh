#!/bin/bash
# Render backend: every Python process of the local compose stack in one container.
# GigSim and the three MCP servers listen on localhost only; the API is the one public port
# ($PORT, set by Render). If any process exits, the container exits and Render restarts it.
# ponytail: one container for the demo deployment; split into private services and a
# background worker (as in infra/docker-compose.yml) when one part needs to scale alone.
set -eu

export MARKETPLACE_MCP_URL="http://127.0.0.1:8200/mcp"
export PORTFOLIO_MCP_URL="http://127.0.0.1:8300/mcp"
export WORKSPACE_MCP_URL="http://127.0.0.1:8400/mcp"
export GIGSIM_URL="http://127.0.0.1:8100"
mkdir -p /tmp/gigbid/audit /tmp/gigbid/workspace
export MARKETPLACE_AUDIT_LOG=/tmp/gigbid/audit/marketplace.jsonl WORKSPACE_DIR=/tmp/gigbid/workspace

uvicorn gigsim.app:create_app --factory --host 127.0.0.1 --port 8100 &
HOST=127.0.0.1 PORT=8200 python -m mcp_servers.marketplace.server &
HOST=127.0.0.1 PORT=8300 python -m mcp_servers.portfolio.server &
HOST=127.0.0.1 PORT=8400 python -m mcp_servers.workspace.server &
uvicorn apps.api.main:create_app --factory --host 0.0.0.0 --port "${PORT:-10000}" \
    --proxy-headers --forwarded-allow-ips='*' &

# The API creates the schema on startup; then the demo account can be seeded.
for _ in $(seq 150); do  # up to 5 minutes
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-10000}/health')" 2>/dev/null && break
    sleep 2
done
if [ -n "${DEMO_EMAIL:-}" ] && [ -n "${DEMO_PASSWORD:-}" ]; then
    python -m apps.api.seed
fi
python -m worker.main &

wait -n || true  # returns when the first process exits
echo "a GigBid process exited; stopping the container so Render restarts it" >&2
exit 1
