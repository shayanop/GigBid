"""What GigBid has learned about you, why, and the controls to forget it."""

from fastapi import APIRouter, Request

from agent.config import load_config
from agent.memory import store as memory
from apps.api.auth import User
from apps.api.schemas import MemoryOut

router = APIRouter(prefix="/memory", tags=["memory"])


def _preference(item: dict) -> dict:
    return {**item, "edits": len(item["edits"])}


@router.get("", response_model=MemoryOut)
async def learned(user: User, request: Request):
    data = await memory.everything(request.app.state.store, user["id"])
    minimum = load_config()["memory"]["outcomes_min_samples"]
    outcomes = []
    for item in data["outcomes"]:
        sent, answered, interviews = memory.outcome_rate(item)
        outcomes.append({"skill": item["skill"], "submitted": sent, "replied": answered,
                         "interview": interviews, "shown_to_agents": sent >= minimum,
                         "reply_rate": answered / sent if sent else None})
    return {"preferences": [_preference(p) for p in data["preferences"]],
            "learning": [_preference(p) for p in data["learning"]],
            "outcomes": sorted(outcomes, key=lambda o: -o["submitted"]),
            "style_min_support": load_config()["memory"]["style_min_support"],
            "outcomes_min_samples": minimum}


@router.delete("/preferences/{key}", status_code=204)
async def forget_preference(key: str, user: User, request: Request):
    """Removes a preference or a candidate, with all its evidence."""
    await memory.forget(request.app.state.store, user["id"], memory.STYLE, key)


@router.delete("/outcomes/{skill}", status_code=204)
async def forget_outcomes(skill: str, user: User, request: Request):
    await memory.forget(request.app.state.store, user["id"], memory.OUTCOMES, skill.lower())
