"""Scoring rules of the experiment runners (E2, A7): no model calls."""

from evals.runners.decision_eval import label, sample, scores
from evals.runners.tool_granularity import score
from gigsim import seed


def test_tool_scoring_pairs_calls_and_checks_arguments():
    two = {"calls": [{"tool": "search_evidence", "args": {"keywords": ["stripe"]}},
                     {"tool": "search_evidence", "args": {"keywords": ["celery"]}}]}
    got = [{"name": "search_evidence", "args": {"requirement": "Celery jobs"}},
           {"name": "search_evidence", "args": {"requirement": "Stripe payments"}}]
    assert score(two, got, coarse=False) == {"selection_ok": True, "args_right": 2,
                                             "args_expected": 2}
    merged = [{"name": "portfolio", "args": {"action": "search", "query": "stripe, celery"}}]
    assert score(two, merged, coarse=True)["selection_ok"] is False  # one call, two expected
    job = {"calls": [{"tool": "get_job", "args": {"job_id": "job_00001"}}]}
    coarse = [{"name": "marketplace", "args": {"action": "get_job", "job_id": "job_00001"}}]
    assert score(job, coarse, coarse=True)["args_right"] == 1
    assert score(job, [{"name": "get_job", "args": {"job_id": "job_00002"}}], False) == {
        "selection_ok": True, "args_right": 0, "args_expected": 1}


def test_decision_labels_and_scores():
    jobs = seed.build()["jobs"]
    pairs = sample(jobs, 10)
    assert len(pairs) == 30 and pairs == sample(jobs, 10)  # fixed by the seed
    rows = [{"persona": p, "job_id": j, "label": label(jobs[j], p), "action": label(jobs[j], p),
             "risk": 0.9 if jobs[j]["_truth"]["scam"] else 0.0, "price": None, "tokens": 1,
             "seconds": 1.0} for p, j in pairs]
    s = scores(rows, jobs)
    assert s["bid_f1"] == 1.0 and s["scam_recall"] == 1.0 and s["scam_precision"] == 1.0
    rows[0] = {**rows[0], "action": "watch"}  # a missed bid lowers recall, not precision
    s = scores(rows, jobs)
    assert s["bid_precision"] == 1.0 and s["bid_recall"] < 1.0


def test_cost_prices_the_model_that_answered():
    from evals.runners.budget_eval import cost
    calls = [{"model": "openai/gpt-oss-20b", "input_tokens": 1_000_000, "output_tokens": 0},
             {"model": "gpt-oss-120b", "input_tokens": 0, "output_tokens": 1_000_000},
             {"model": "nvidia/nemotron-3-ultra-550b-a55b", "input_tokens": 5, "output_tokens": 5}]
    usd, unpriced = cost(calls)
    assert round(usd, 3) == 0.825 and unpriced == 1  # Groq 20b input + Cerebras 120b output


def test_smoke_gates():
    from evals.runners.smoke import gate
    gates = {"min_bid_f1": 0.7, "max_unsupported_per_proposal": 0.5,
             "min_proposals_measured": 2, "max_errors": 3}
    good = gate({"bid_f1": 0.8, "errors": 1},
                {"after_verification": {"unsupported_per_proposal": 0.0}, "proposals_measured": 3},
                gates)
    assert all(c["ok"] for c in good.values())
    bad = gate({"bid_f1": 0.6, "errors": 0}, {"after_verification": None, "proposals_measured": 0},
               gates)
    assert not bad["bid_f1"]["ok"] and not bad["unsupported_per_proposal"]["ok"]
