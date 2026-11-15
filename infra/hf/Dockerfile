# Hugging Face Docker Space: the whole stack in one container (web, API, worker, GigSim,
# three MCP servers, Postgres, Redis). infra/hf/push.py uploads this file as the Space's
# root Dockerfile. The web app listens on 7860 (app_port in the Space card).
FROM node:24.22.1-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json apps/web/.npmrc ./
RUN npm ci
COPY apps/web ./
# Next reads the proxy target at build time; the API runs in the same container.
ENV API_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN npx next build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends postgresql redis-server \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app
ENV UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH FASTEMBED_CACHE_PATH=/models
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY . .
RUN OMP_NUM_THREADS=1 python -c "from rag.retriever import warm_all; print('indexes:', warm_all())" \
    && chmod +x infra/render/start.sh infra/hf/start.sh
COPY --from=web /web /web
RUN chown -R user /app /models /web
USER user
# The Space is served over https and may be embedded in huggingface.co, so the session
# cookie must be Secure and SameSite=None. GIGBID_PROFILE=open is the spec's default.
ENV COOKIE_SECURE=1 COOKIE_SAMESITE=none GIGBID_PROFILE=open NODE_ENV=production
EXPOSE 7860
CMD ["./infra/hf/start.sh"]
