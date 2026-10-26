"""Pricing Strategist: market median for similar jobs, the user's floor, the client's
posted max and expected Connects value. Deterministic, so it costs no tokens."""

import statistics

from agent.config import load_config
from agent.handoffs import PriceQuote
from agent.nodes import common


@common.node("pricing")
async def quote(state: dict) -> dict:
    job, fit = state["job"], state["fit"]
    cfg = load_config()
    rules, fees = cfg["pricing"], cfg["fees"]
    page = await common.toolbox().call("pricing", "marketplace", "search_jobs",
                                       {"skills": job.skills[:10], "limit": 50})
    peers = [j["budget_max"] for j in page["jobs"]
             if j["budget_type"] == job.budget_type and j["budget_max"] and j["id"] != job.id]
    hourly = job.budget_type == "hourly"
    floor = rules["hourly_rate_floor"] if hourly else rules["fixed_bid_floor"]
    market = statistics.median(peers) if peers else job.budget_max or floor
    target = market * (1.0 if fit.score >= 0.8 else 0.9)
    notes = [f"median of {len(peers)} similar {job.budget_type} jobs is {market:.0f} USD"]
    if job.budget_max and target > job.budget_max:
        target = job.budget_max
        notes.append(f"capped at the client's max {job.budget_max:.0f}")
    if target < floor:
        notes.append(f"raised to your floor {floor} (client budget is below it)")
    amount = round(max(target, floor))
    p_win = rules["win_rate_at_full_fit"] * fit.score
    net = amount * (rules["assumed_hours"] if hourly else 1) * (1 - fees["platform_fee_pct"] / 100)
    connects_usd = job.connects_cost * fees["connect_price_usd"]
    ev = round(p_win * net - connects_usd, 2)
    notes.append(f"P(win) {p_win:.0%} x {net:.0f} net - {connects_usd:.2f} Connects = {ev} USD")
    return {"price": PriceQuote(amount=amount, budget_type=job.budget_type,
                                connects_cost=job.connects_cost, expected_value_usd=ev,
                                rationale="; ".join(notes))}
