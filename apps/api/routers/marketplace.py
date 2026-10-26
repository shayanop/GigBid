"""Marketplace health for the UI's degraded mode, plus the user's Connects balance."""

from fastapi import APIRouter, Request

from agent.mcp_client import ToolCallError
from apps.api.auth import User
from apps.api.schemas import MarketplaceStatus

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get("", response_model=MarketplaceStatus)
async def status(user: User, request: Request):
    toolbox = request.app.state.toolbox_for(user["account"], request.state.trace_id)
    try:
        balance = await toolbox.call("scout", "marketplace", "get_connects_balance", {})
    except (ToolCallError, OSError, TimeoutError):
        return {"available": False, "connects": None}
    return {"available": True, "connects": balance["balance"]}
