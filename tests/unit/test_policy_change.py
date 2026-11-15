"""Policy change v2 (docs/DESIGN_REVIEW.md, section 6): GigSim doubles Connects costs and
refuses proposals with external links; GigBid's Compliance Guard removes link sentences
before a draft reaches approval, and pricing reads the new cost from the marketplace."""

from fastapi.testclient import TestClient

from agent.nodes.compliance import scrub
from gigsim import app as gigsim_app

HEADERS = {"Authorization": "Bearer fr_ml"}


def _write(letter: str) -> dict:
    return {**HEADERS, "Idempotency-Key": f"key-{hash(letter)}"}


def _proposal(api: TestClient, letter: str) -> str:
    body = {"job_id": "job_00012", "cover_letter": letter, "bid_amount": 500,
            "screening_answers": []}
    return api.post("/proposals", json=body, headers=_write(letter)).json()["id"]


def test_policy_v2_doubles_connects_and_refuses_links(monkeypatch):
    before = TestClient(gigsim_app.create_app()).get("/jobs/job_00012", headers=HEADERS).json()
    monkeypatch.setenv("GIGSIM_POLICY", "v2")
    api = TestClient(gigsim_app.create_app())
    assert api.get("/jobs/job_00012", headers=HEADERS).json()["connects_cost"] == (
        2 * before["connects_cost"])
    linked = _proposal(api, "See my work at github.com/sana/rag-demo for details.")
    refused = api.post(f"/proposals/{linked}/submit", headers=_write(linked))
    assert refused.status_code == 422 and "external links" in refused.json()["detail"]
    plain = _proposal(api, "I built a retrieval pipeline for a legal client.")
    assert api.post(f"/proposals/{plain}/submit", headers=_write(plain)).status_code == 200


def test_compliance_drops_link_sentences():
    letter, removed = scrub("I built a RAG system. The code is at https://github.com/x/y. "
                            "Happy to talk on a call.")
    assert "github" not in letter and "Happy to talk" in letter
    assert removed == ["external links"]
