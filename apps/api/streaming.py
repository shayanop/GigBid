"""Graph progress over Redis pub/sub: the worker publishes per-node events, the API
relays them to the browser as Server-Sent Events."""

import json

from fastapi import Request
from fastapi.sse import ServerSentEvent

FINAL = {"done", "interrupt"}


def channel(thread_id: str) -> str:
    return f"run:{thread_id}"


async def publish(redis, thread_id: str, event: dict) -> None:
    await redis.publish(channel(thread_id), json.dumps(event, default=str))


async def relay(request: Request, thread_id: str, snapshot):
    """Yields a snapshot of the run so far, then live events until it pauses or ends.
    Subscribes before reading the snapshot so no event falls in between."""
    pubsub = request.app.state.redis.pubsub()
    await pubsub.subscribe(channel(thread_id))
    try:
        first = await snapshot()
        yield ServerSentEvent(event="snapshot", data=first)
        if first["status"] not in ("queued", "analyzing", "drafting", "processing"):
            return
        while not await request.is_disconnected():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
            if message is None:
                yield ServerSentEvent(comment="keepalive")
                continue
            event = json.loads(message["data"])
            yield ServerSentEvent(event=event.get("event", "node"), data=event)
            if event.get("event") in FINAL:
                return
    finally:
        await pubsub.unsubscribe(channel(thread_id))
        await pubsub.aclose()
