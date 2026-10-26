"""Bearer-token auth shared by GigBid's MCP servers."""

import json
import os

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError


class StaticTokens:
    """Bearer token -> user id, from <PREFIX>_MCP_TOKENS ({"token": "user_id"})."""

    # ponytail: static map; swap for the API's user/session store once it exists.
    def __init__(self, tokens: dict[str, str]):
        self.tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        user = self.tokens.get(token)
        return AccessToken(token=token, client_id=user, scopes=[]) if user else None


def static_auth(prefix: str, url: str) -> dict:
    """MCPServer kwargs requiring a bearer token on the HTTP transport."""
    return {
        "token_verifier": StaticTokens(json.loads(os.getenv(f"{prefix}_MCP_TOKENS", "{}"))),
        "auth": AuthSettings(issuer_url=url.removesuffix("/mcp"), resource_server_url=url,
                             validate_token_resource=False),  # static tokens carry no audience
    }


def current_user(prefix: str) -> str:
    if token := get_access_token():
        return token.client_id
    # In-process and stdio transports carry no bearer token; HTTP always does.
    if user := os.getenv(f"{prefix}_LOCAL_USER"):
        return user
    raise ToolError("unauthenticated")
