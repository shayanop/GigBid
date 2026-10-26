import asyncio

from mcp_servers.auth import SignedTokens, mint


def test_signed_tokens_verify_and_reject_tampering(monkeypatch):
    monkeypatch.setenv("MCP_SIGNING_SECRET", "s3cret")
    verify = SignedTokens().verify_token
    good = mint("fr_ml", ttl_seconds=60)
    assert asyncio.run(verify(good)).client_id == "fr_ml"
    assert asyncio.run(verify(good.replace("fr_ml", "fr_fs", 1))) is None  # other account
    assert asyncio.run(verify(mint("fr_ml", ttl_seconds=-1))) is None  # expired
    assert asyncio.run(verify("garbage")) is None
    monkeypatch.setenv("MCP_SIGNING_SECRET", "rotated")
    assert asyncio.run(verify(good)) is None
