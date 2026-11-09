import os

import pytest
from pydantic import BaseModel

from agent.config import LLM_NODES, get_model, load_config, model_spec


def test_profile_overrides_name_real_nodes():
    for name, profile in load_config()["profiles"].items():
        assert set(profile.get("nodes", {})) | set(profile.get("thinking", [])) <= LLM_NODES, name


@pytest.mark.parametrize("profile", list(load_config()["profiles"]))
def test_every_node_builds_in_every_profile(profile, monkeypatch):
    monkeypatch.setenv("GIGBID_PROFILE", profile)
    monkeypatch.setenv("GROQ_API_KEY", os.getenv("GROQ_API_KEY") or "test-placeholder")
    monkeypatch.setenv("NIM_API_KEY", os.getenv("NIM_API_KEY") or "test-placeholder")
    for node in LLM_NODES:
        assert get_model(node) is not None


def test_heavy_nodes_skip_fallback_and_cheap_nodes_get_one(monkeypatch):
    monkeypatch.setenv("GIGBID_PROFILE", "open")
    assert model_spec("writer") == ("groq:openai/gpt-oss-120b", None)
    assert model_spec("risk")[1] is not None


def test_nim_profile_uses_nim_only_for_writer_and_critic_with_groq_backup(monkeypatch):
    monkeypatch.setenv("GIGBID_PROFILE", "nim")
    on_nim = {n for n in LLM_NODES if model_spec(n)[0].startswith("nvidia:")}
    assert on_nim == {"writer", "critic"}
    for node in on_nim:
        assert model_spec(node)[1] == "groq:openai/gpt-oss-120b"


def test_several_groq_keys_shift_on_rate_limit(monkeypatch):
    from groq import RateLimitError
    monkeypatch.setenv("GIGBID_PROFILE", "open")
    monkeypatch.setenv("GROQ_API_KEYS", "key-a, key-b,key-c")
    llm = get_model("writer")  # no node fallback, so the key chain is the whole model
    clients = [llm.runnable, *llm.fallbacks]
    assert [c.groq_api_key.get_secret_value() for c in clients] == ["key-a", "key-b", "key-c"]
    assert [c.max_retries for c in clients] == [0, 0, 2]
    assert llm.exceptions_to_handle == (RateLimitError,)


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


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("NIM_API_KEY"), reason="NIM_API_KEY not set")
def test_nim_structured_output(monkeypatch):
    monkeypatch.setenv("GIGBID_PROFILE", "nim")
    out = get_model("writer", Echo).invoke("Return the word 'gigbid' in the `word` field.")
    assert out["raw"].response_metadata["model_name"].startswith("nvidia/")  # not the backup
    assert out["parsed"].word.lower() == "gigbid"
    assert out["raw"].usage_metadata["total_tokens"] > 0
