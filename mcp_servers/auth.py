"""Bearer-token auth shared by GigBid's MCP servers.

Tokens are "<account>.<expiry>.<hmac>" signed with MCP_SIGNING_SECRET, so the API and
worker can mint a short-lived token per user without a token table. External hosts
get a longer-lived one: python -m mcp_servers.auth fr_ml --days 30
"""

import argparse
import hashlib
import hmac
import os
import re
import time

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError

ACCOUNT = re.compile(r"[\w-]{1,64}")


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def mint(account: str, ttl_seconds: int = 3600, secret: str | None = None) -> str:
    if not ACCOUNT.fullmatch(account):
        raise ValueError(f"invalid account {account!r}")
    payload = f"{account}.{int(time.time()) + ttl_seconds}"
    return f"{payload}.{_sign(payload, secret or os.environ['MCP_SIGNING_SECRET'])}"


class SignedTokens:
    async def verify_token(self, token: str) -> AccessToken | None:
        secret = os.getenv("MCP_SIGNING_SECRET")
        try:
            account, expiry, signature = token.rsplit(".", 2)
        except ValueError:
            return None
        if (not secret or not ACCOUNT.fullmatch(account) or not expiry.isdigit()
                or int(expiry) < time.time()
                or not hmac.compare_digest(signature, _sign(f"{account}.{expiry}", secret))):
            return None
        return AccessToken(token=token, client_id=account, scopes=[], expires_at=int(expiry))


def bearer_auth(url: str) -> dict:
    """MCPServer kwargs requiring a signed bearer token on the HTTP transport."""
    return {
        "token_verifier": SignedTokens(),
        "auth": AuthSettings(issuer_url=url.removesuffix("/mcp"), resource_server_url=url,
                             validate_token_resource=False),  # tokens carry no audience
    }


def current_user(prefix: str) -> str:
    if token := get_access_token():
        return token.client_id
    # In-process and stdio transports carry no bearer token; HTTP always does.
    if user := os.getenv(f"{prefix}_LOCAL_USER"):
        return user
    raise ToolError("unauthenticated")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Mint an MCP bearer token for an account")
    parser.add_argument("account")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    print(mint(args.account, args.days * 86400))
