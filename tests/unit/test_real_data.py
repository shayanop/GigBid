import json

from fastapi.testclient import TestClient

from data.real import prepare
from evals.runners import scam_eval
from gigsim import app as gigsim_app
from gigsim import seed


def test_category_matches_whole_words_only():
    assert prepare.category("Excellent writer for our blog") == "other"
    assert prepare.category("PostgreSQL admin for a web application") == "fullstack"
    assert prepare.category("Power BI dashboard from SQL") == "data"
    assert prepare.category("AI chatbot with LangChain") == "ml"


def test_upwork_tags_map_onto_the_persona_vocabulary():
    tags = ["Microsoft Power BI", "Amazon Web Services", "MySQL", "Python",
            "Retrieval Augmented Generation"]
    assert prepare.vocab_skills(tags) == ["AWS", "Power BI", "Python", "RAG"]  # MySQL is not SQL


def test_money_and_the_50k_metadata_tail():
    assert prepare.money("$2,500 ") == 2500 and prepare.money("0") is None
    body, tags, cat = prepare.parse_50k(
        "We need a dashboard.Budget: $500Posted On: Feb 17, 2024Category: Data AnalyticsSkills:"
        "Tableau,     SQLSkills:        Tableau,          SQLCountry: United Statesclick to apply")
    assert (body, tags, cat) == ("We need a dashboard.", ["Tableau", "SQL"], "Data Analytics")


def test_gigsim_real_mode_serves_real_records_and_hides_provenance(tmp_path, monkeypatch):
    client = {"id": "rc_1", "name": "Upwork client 1", "country": "Canada",
              "payment_verified": True, "total_spend": 1200.0, "hire_rate": 0.5,
              "jobs_posted": 3, "rating": 4.9, "reviews": [], "member_since": "2022-01-01T00:00:00",
              "_prefs": {"dislikes_generic_opening": True, "budget_ceiling_pct": 1.0},
              "_source": "upwork-60k", "_synthetic": ["hire_rate"]}
    job = {"id": "rj_1", "title": "Power BI report", "description": "Refine our report.",
           "skills": ["Microsoft Power BI"], "budget_type": "fixed", "budget_min": None,
           "budget_max": 200.0, "posted_at": "2023-03-15T00:00:00", "connects_cost": 4,
           "client_id": "rc_1", "screening_questions": [],
           "_truth": {"category": "data", "scam": None}, "_source": "upwork-60k"}
    path = tmp_path / "gigsim.jsonl"
    path.write_text(json.dumps({"job": job, "client": client}) + "\n", encoding="utf-8")
    monkeypatch.setattr(seed.load_real, "__defaults__", (path, 42))  # the default path
    monkeypatch.setenv("GIGSIM_DATA", "real")
    api = TestClient(gigsim_app.create_app())
    headers = {"Authorization": "Bearer fr_da"}
    got = api.get("/jobs/rj_1", headers=headers).json()
    assert got["title"] == "Power BI report" and "_source" not in got and "_truth" not in got
    assert api.get("/clients/rc_1", headers=headers).json()["total_spend"] == 1200.0


def test_scam_scores_split_templated_fakes():
    rows = [{"fraudulent": 1, "templated": True}, {"fraudulent": 1, "templated": False},
            {"fraudulent": 0, "templated": False}, {"fraudulent": 0, "templated": False}]
    s = scam_eval.scores(rows, [True, False, True, False])
    assert (s["precision"], s["recall"], s["false_positive_rate"]) == (0.5, 0.5, 0.5)
    assert (s["recall_templated_fakes"], s["recall_other_fakes"]) == (1.0, 0.0)


def test_crypto_is_a_payment_flag_only_in_a_payment_phrase():
    import re

    from agent.nodes.risk import RULES
    rx = re.compile(RULES["off_platform_payment"], re.IGNORECASE)
    assert rx.search("Payment will be made in crypto outside the platform to avoid fees.")
    assert rx.search("Paid weekly either in crypto or wire.")
    assert not rx.search("Build a volatility prediction model for crypto assets.")
