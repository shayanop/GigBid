"""Durable checkpoints for both graphs (C6)."""

import os
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from agent import handoffs, marketplace_port
from rag import schema


def serde() -> JsonPlusSerializer:
    """Deserializes only GigBid's own state models (plus LangGraph's safe built-ins), so a
    tampered checkpoint cannot instantiate arbitrary classes."""
    allowed = [(m.__name__, name) for m in (handoffs, marketplace_port, schema)
               for name, obj in vars(m).items()
               if isinstance(obj, type) and issubclass(obj, BaseModel)
               and obj.__module__ == m.__name__]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


@asynccontextmanager
async def migration_lock(url: str | None = None):
    """Serializes schema setup across processes: the API and the worker start together,
    and concurrent CREATE ... IF NOT EXISTS can still collide in Postgres."""
    async with await psycopg.AsyncConnection.connect(url or os.environ["DATABASE_URL"],
                                                     autocommit=True) as conn:
        await conn.execute("SELECT pg_advisory_lock(7140021)")
        try:
            yield
        finally:
            await conn.execute("SELECT pg_advisory_unlock(7140021)")


@asynccontextmanager
async def postgres_checkpointer(url: str | None = None):
    async with AsyncPostgresSaver.from_conn_string(url or os.environ["DATABASE_URL"],
                                                   serde=serde()) as saver:
        async with migration_lock(url):
            await saver.setup()
        yield saver
