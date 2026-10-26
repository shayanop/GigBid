"""Durable checkpoints for both graphs (C6)."""

import os
from contextlib import asynccontextmanager

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
async def postgres_checkpointer(url: str | None = None):
    async with AsyncPostgresSaver.from_conn_string(url or os.environ["DATABASE_URL"],
                                                   serde=serde()) as saver:
        await saver.setup()
        yield saver
