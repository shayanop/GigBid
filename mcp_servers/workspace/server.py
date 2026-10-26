"""Workspace MCP server (A3): free calendar slots, tentative interview holds and email
drafts. Backed by a local mock calendar per account; agents only see the MCP interface,
so Google Calendar and Gmail can replace the mock without touching the graphs.

Run: python -m mcp_servers.workspace.server  (Streamable HTTP, /mcp)
"""

import json
import os
import random
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.auth import bearer_auth, current_user

READ = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                        open_world_hint=False)
IdemKey = Annotated[str, Field(min_length=8, max_length=128, description=(
    "Unique key for this intended write. Reuse the same key when retrying it."))]

URL = os.getenv("WORKSPACE_MCP_URL", "http://localhost:8400/mcp")
mcp = MCPServer(
    "gigbid-workspace",
    instructions="The freelancer's calendar and email drafts. Times are UTC. Holds are "
                 "tentative until the freelancer confirms them.",
    **bearer_auth(URL),
)
_lock = threading.Lock()  # ponytail: one process; a real calendar API serializes for us


class Slot(BaseModel):
    start: datetime
    end: datetime


class Event(Slot):
    id: str
    title: str
    status: Literal["busy", "tentative"]


class EmailDraft(BaseModel):
    id: str
    to: str | None
    subject: str
    body: str
    created_at: datetime


def _path(account: str) -> Path:
    return Path(os.getenv("WORKSPACE_DIR", "data/processed/workspace")) / f"{account}.json"


def _seed(account: str) -> list[dict]:
    """A plausible working calendar: one to three meetings on each weekday ahead."""
    rng, events = random.Random(account), []
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(1, 22):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for n in range(rng.randint(1, 3)):
            start = day + timedelta(hours=rng.randint(9, 16))
            events.append({"id": f"busy-{offset}-{n}", "title": rng.choice(
                ["Client work", "Standup", "Code review", "Focus block"]), "status": "busy",
                "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()})
    return events


def _load(account: str) -> dict:
    path = _path(account)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"events": _seed(account), "drafts": [], "writes": {}}


def _save(account: str, data: dict) -> None:
    path = _path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _overlaps(start: datetime, end: datetime, events: list[dict]) -> bool:
    return any(start < datetime.fromisoformat(e["end"]) and datetime.fromisoformat(e["start"]) < end
               for e in events)


@mcp.tool(annotations=READ)
async def find_free_slots(
    duration_minutes: Annotated[int, Field(ge=15, le=240)] = 30,
    days_ahead: Annotated[int, Field(ge=1, le=21)] = 7,
    limit: Annotated[int, Field(ge=1, le=10)] = 3,
    earliest_hour: Annotated[int, Field(ge=0, le=23)] = 9,
    latest_hour: Annotated[int, Field(ge=1, le=24)] = 17,
) -> list[Slot]:
    """Free weekday slots (UTC), at most one per day so the client gets real options."""
    account = current_user("WORKSPACE")
    events = _load(account)["events"]
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    length, slots = timedelta(minutes=duration_minutes), []
    for offset in range(1, days_ahead + 1):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        start = day + timedelta(hours=earliest_hour)
        while start + length <= day + timedelta(hours=latest_hour):
            if not _overlaps(start, start + length, events):
                slots.append(Slot(start=start, end=start + length))
                break
            start += timedelta(minutes=30)
        if len(slots) == limit:
            break
    return slots


@mcp.tool(annotations=WRITE)
async def hold_slot(start: datetime, end: datetime,
                    title: Annotated[str, Field(min_length=1, max_length=200)],
                    idempotency_key: IdemKey) -> Event:
    """Put a tentative hold on the calendar, e.g. an interview time offered to a client."""
    account = current_user("WORKSPACE")
    if end <= start:
        raise ToolError("end must be after start")
    with _lock:
        data = _load(account)
        if idempotency_key in data["writes"]:
            return Event.model_validate(data["writes"][idempotency_key])
        if _overlaps(start, end, data["events"]):
            raise ToolError("that time is no longer free")
        event = Event(id=f"hold-{len(data['events']) + 1}", title=title, status="tentative",
                      start=start, end=end)
        data["events"].append(event.model_dump(mode="json"))
        data["writes"][idempotency_key] = event.model_dump(mode="json")
        _save(account, data)
    return event


@mcp.tool(annotations=WRITE)
async def create_email_draft(subject: Annotated[str, Field(min_length=1, max_length=200)],
                             body: Annotated[str, Field(min_length=1, max_length=10_000)],
                             idempotency_key: IdemKey, to: str | None = None) -> EmailDraft:
    """Save an email draft for the freelancer to review and send themselves."""
    account = current_user("WORKSPACE")
    with _lock:
        data = _load(account)
        if idempotency_key in data["writes"]:
            return EmailDraft.model_validate(data["writes"][idempotency_key])
        draft = EmailDraft(id=f"draft-{len(data['drafts']) + 1}", to=to, subject=subject,
                           body=body, created_at=datetime.now(UTC))
        data["drafts"].append(draft.model_dump(mode="json"))
        data["writes"][idempotency_key] = draft.model_dump(mode="json")
        _save(account, data)
    return draft


if __name__ == "__main__":
    mcp.run("streamable-http", host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8400")))
