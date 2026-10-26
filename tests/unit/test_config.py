import os

import pytest
from pydantic import BaseModel

from agent.config import LLM_NODES, get_model, load_config, model_spec


def test_profile_overrides_name_real_nodes():
    for name, profile in load_config()["profiles"].items():
        assert set(profile.get("nodes", {})) <= LLM_NODES, name


@pytest.mark.parametrize("profile", list(load_config()["profiles"]))
def test_every_node_builds_in_every_profile(profile, monkeypatch):
    monkeypatch.setenv("GIGBID_PROFILE", profile)
    monkeypatch.setenv("GROQ_API_KEY", os.getenv("GROQ_API_KEY") or "test-placeholder")
    for node in LLM_NODES:
        assert get_model(node) is not None


def test_heavy_nodes_skip_fallback_and_cheap_nodes_get_one(monkeypatch):
    monkeypatch.setenv("GIGBID_PROFILE", "open")
    assert model_spec("writer") == ("groq:openai/gpt-oss-120b", None)
    assert model_spec("risk")[1] is not None


def test_unknown_node_is_rejected():
    with pytest.raises(KeyError):
        model_spec("wirter")


class Echo(BaseModel):
    word: str


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_groq_structured_output():
    out = get_model("analyst", Echo).invoke("Return the word 'gigbid' in the `word` field.")
    assert out["parsed"].word.lower() == "gigbid"
    assert out["raw"].usage_metadata["total_tokens"] > 0


def test_api_module_builds_nothing_at_import():
    # CI has no .env: importing the API must not read secrets or open connections.
    from apps.api import main
    assert not hasattr(main, "app") and callable(main.create_app)
