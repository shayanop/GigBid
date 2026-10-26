from agent.redact import redact
from gigsim import seed


def test_redact_masks_pii_but_keeps_ids_dates_and_amounts():
    text = "Mail a.b@x.io or call +1 415 555 0100, job_00012 posted 2026-10-01T12:00:00 for 1500.0"
    out = redact({"m": [text], "n": 250000.5})
    assert "a.b@x.io" not in out["m"][0] and "555 0100" not in out["m"][0]
    assert "job_00012" in out["m"][0] and "2026-10-01T12:00:00" in out["m"][0]
    assert "1500.0" in out["m"][0] and out["n"] == 250000.5


def test_seed_is_deterministic_and_has_hard_cases():
    a, b = seed.build(), seed.build()
    assert a["jobs"] == b["jobs"]
    truths = [j["_truth"] for j in a["jobs"].values()]
    assert sum(t["scam"] for t in truths) > 20
    assert sum(t["injection"] for t in truths) > 10
    assert sum(t["duplicate_of"] is not None for t in truths) > 10
    assert {t["category"] for t in truths} == {"ml", "fullstack", "data", "other"}
