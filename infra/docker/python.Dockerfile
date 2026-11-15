# One image for every Python service; compose picks the command, Render runs
# infra/render/start.sh (all of them in one container).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH FASTEMBED_CACHE_PATH=/models
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY . .
# Bake the embedding model and every persona's index into the image, so a fresh container
# (a Render deploy, or compose's empty volumes, which Docker fills from here) starts in
# seconds instead of downloading and embedding first.
RUN OMP_NUM_THREADS=1 python -c "from rag.retriever import warm_all; print('indexes:', warm_all())" \
    && chmod +x infra/render/start.sh
