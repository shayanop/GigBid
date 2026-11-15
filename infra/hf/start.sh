#!/bin/bash
# Hugging Face Space: start Postgres and Redis in the container (unless DATABASE_URL or
# REDIS_URL point elsewhere), then the web app on 7860 and the backend from the Render
# script. If the web app or any backend process exits, the container exits and restarts.
# ponytail: local Postgres lives in /tmp, so a restart resets it and re-seeds the demo.
# Set DATABASE_URL to an external Postgres (e.g. Neon's free tier) to keep data.
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
    PGBIN=$(ls -d /usr/lib/postgresql/*/bin)
    PGDATA=/tmp/pgdata
    [ -f "$PGDATA/PG_VERSION" ] || "$PGBIN/initdb" -D "$PGDATA" -U gigbid --auth=trust >/dev/null
    "$PGBIN/pg_ctl" -D "$PGDATA" -l /tmp/postgres.log -w \
        -o "-k /tmp -c listen_addresses=127.0.0.1" start
    "$PGBIN/createdb" -h 127.0.0.1 -U gigbid gigbid 2>/dev/null || true
    export DATABASE_URL=postgresql://gigbid@127.0.0.1:5432/gigbid
fi
if [ -z "${REDIS_URL:-}" ]; then
    redis-server --bind 127.0.0.1 --port 6379 --save '' --appendonly no >/tmp/redis.log &
    export REDIS_URL=redis://127.0.0.1:6379
fi

# Secrets the Space did not set: random per start (sessions end on restart).
random() { python -c "import secrets; print(secrets.token_hex(32))"; }
export SESSION_SECRET="${SESSION_SECRET:-$(random)}"
export MCP_SIGNING_SECRET="${MCP_SIGNING_SECRET:-$(random)}"

(cd /web && HOSTNAME=0.0.0.0 node node_modules/next/dist/bin/next start --port 7860) &
PORT=8000 ./infra/render/start.sh &

wait -n || true
echo "a GigBid process exited; stopping the container so the Space restarts it" >&2
exit 1
