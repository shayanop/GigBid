from fastapi.testclient import TestClient

from gigsim.app import create_app

AUTH = {"Authorization": "Bearer fr_ml"}


def _submit(client: TestClient, job_id: str, letter: str, bid: float) -> None:
    draft = client.post("/proposals", headers={**AUTH, "Idempotency-Key": f"d-{job_id}-{bid}"},
                        json={"job_id": job_id, "cover_letter": letter, "bid_amount": bid})
    client.post(f"/proposals/{draft.json()['id']}/submit",
                headers={**AUTH, "Idempotency-Key": f"s-{job_id}-{bid}"})


def test_clients_react_to_price_and_generic_openings_deterministically():
    app = create_app(n_jobs=300)
    jobs = [j for j in app.state.data["jobs"].values()
            if app.state.data["clients"][j["client_id"]]["_prefs"] and j["budget_max"]][:30]
    with TestClient(app) as client:
        before = len(app.state.data["threads"])
        for job in jobs[:15]:  # fair bids, specific openings
            _submit(client, job["id"], "You need a dbt layer; I built one last year.", job["budget_max"] * 0.8)
        fair = len(app.state.data["threads"]) - before
        for job in jobs[15:]:  # overpriced and generic
            _submit(client, job["id"], "Dear Sir, I am an expert. Check my profile.", job["budget_max"] * 3)
        greedy = len(app.state.data["threads"]) - before - fair
    assert fair > greedy
    new = list(app.state.data["threads"].values())[before:]
    assert {t["_intent"] for t in new} <= {"interview", "question"}
    assert all(t["messages"][0]["sender"] == "client" for t in new)


def test_scam_clients_ask_to_leave_the_platform():
    app = create_app(n_jobs=300)
    job = next(j for j in app.state.data["jobs"].values()
               if app.state.data["clients"][j["client_id"]]["_prefs"] is None)
    with TestClient(app) as client:
        _submit(client, job["id"], "Happy to help.", 100)
    thread = list(app.state.data["threads"].values())[-1]
    assert thread["_intent"] == "scam" and "WhatsApp" in thread["messages"][0]["body"]
