"""Portfolio MCP server over an in-memory MCP client, with an offline embedder."""

import pytest
from mcp import Client

from mcp_servers.portfolio import server


@pytest.fixture(autouse=True)
def persona(monkeypatch, offline_rag):
    monkeypatch.setenv("PORTFOLIO_LOCAL_USER", "fr_ml")


async def call(tool: str, **args):
    async with Client(server.mcp) as client:
        return await client.call_tool(tool, args)


async def test_search_evidence_returns_citable_evidence():
    result = await call("search_evidence", requirement="LangGraph agent with human approval",
                        k=4)
    hits = result.structured_content["result"]
    assert len(hits) == 4 and all(h["persona"] == "fr_ml" for h in hits)
    assert {"id", "type", "source", "date", "outcome", "score", "text"} <= hits[0].keys()


async def test_search_evidence_filters():
    hits = (await call("search_evidence", requirement="fine-tune a model", k=5,
                       filters={"types": ["proposal"], "outcomes": ["won"]})
            ).structured_content["result"]
    assert hits and all(h["type"] == "proposal" and h["outcome"] == "won" for h in hits)
    bad = await call("search_evidence", requirement="x" * 10, filters={"secret": 1})
    assert bad.is_error


async def test_case_study_skills_resources_and_prompt():
    case = (await call("get_case_study", case_id="fr_ml-p01")).structured_content
    assert case["type"] == "case_study" and case["text"].startswith("# ")
    assert (await call("get_case_study", case_id="fr_ml-prop001")).is_error
    skills = (await call("list_skills")).structured_content["result"]
    assert skills and all(s["documents"] > 0 for s in skills)

    async with Client(server.mcp) as client:
        doc = await client.read_resource("portfolio://proposal/fr_ml-prop001")
        assert doc.contents[0].text.startswith("Outcome: ")
        prompt = await client.get_prompt("answer_screening_question",
                                         {"question": "Have you used Pinecone?"})
        assert "search_evidence" in prompt.messages[0].content.text


async def test_unknown_persona_is_refused(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_LOCAL_USER", "nobody")
    assert (await call("list_skills")).is_error
