"""GigBid API. Graph runs never happen in request handlers: handlers queue work for the
worker and read state from the Postgres checkpointer.

Run: uv run uvicorn apps.api.main:app --port 8000
"""

import os
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from arq import create_pool
from arq.connections import RedisSettings
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from starlette.middleware.sessions import SessionMiddleware

from agent.graphs import bid_graph
from agent.graphs.checkpoint import postgres_checkpointer
from agent.mcp_client import Toolbox
from apps.api import db
from apps.api.routers import approvals, auth, jobs, marketplace, runs, searches

load_dotenv()
TRACE_ID = re.compile(r"[\w-]{8,64}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await db.open_pool()
    app.state.redis = Redis.from_url(os.environ["REDIS_URL"])
    app.state.queue = await create_pool(RedisSettings.from_dsn(os.environ["REDIS_URL"]))
    if not hasattr(app.state, "toolbox_for"):
        app.state.toolbox_for = Toolbox.for_user
    try:
        async with postgres_checkpointer() as saver:
            app.state.graph = bid_graph.build(saver)
            yield
    finally:
        await app.state.queue.aclose()
        await app.state.redis.aclose()
        await app.state.db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="GigBid API", version="0.1.0", lifespan=lifespan,
                  # Readable names in the generated TypeScript client, e.g. jobsInbox.
                  generate_unique_id_function=lambda route: f"{route.tags[0]}_{route.name}")
    app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"],
                       same_site="lax", https_only=os.getenv("COOKIE_SECURE") == "1",
                       max_age=14 * 86400)

    @app.middleware("http")
    async def trace_id(request: Request, call_next):
        """One trace id from the browser through API, worker, graph nodes and MCP audit."""
        given = request.headers.get("x-trace-id", "")
        request.state.trace_id = given if TRACE_ID.fullmatch(given) else uuid4().hex
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.get("/health", tags=["health"], include_in_schema=False)
    async def health(request: Request) -> dict:
        await db.fetchone(request.app.state.db, "SELECT 1")
        await request.app.state.redis.ping()
        return {"status": "ok"}

    for router in (auth.router, jobs.router, approvals.router, runs.router, searches.router,
                   marketplace.router):
        app.include_router(router)
    return app


app = create_app()
