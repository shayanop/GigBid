# One image for every Python service; compose picks the command.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY . .
