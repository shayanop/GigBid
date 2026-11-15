"""Latency and cost budgets (E5), measured on held-out jobs: real Upwork postings
(GIGSIM_DATA=real, data/real/prepare.py) that no prompt, threshold or retriever choice was
tuned on. The bid graph runs as deployed (GIGBID_PROFILE, default cerebras) up to the
approval step, and every model call is priced from the model that actually answered
(agent/config.yaml `prices`) against the declared `targets`.

- Analysed job: job in, bid/watch/skip decision out (every job).
- Drafted proposal: job in, proposal awaiting approval (bid jobs only).
- Early skip, the optimization measured here: watch and skip jobs stop after the decision,
  so they never pay for pricing, writer, verifier, critic and compliance.

Run: uv run python -m evals.runners.budget_eval [--per-persona 8]
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime

from langgraph.checkpoint.memory import InMemorySaver

from agent.config import load_config, profile_name
from agent.graphs import bid_graph
from agent.graphs.checkpoint import serde
from agent.mcp_client import Toolbox
from agent.nodes import common
from evals.runners.decision_eval import CATEGORY, as_persona, gigsim_app
from evals.runners.rag_eval import RESULTS
from mcp_servers.marketplace import server as marketplace
from mcp_servers.portfolio import server as portfolio

ANALYSIS = {"scout", "analyst", "risk", "matcher", "decide"}


def cost(calls: list[dict]) -> tuple[float, int]:
    """USD for these model calls, and how many came from a model with no listed price."""
    prices, usd, unpriced = load_config()["prices"], 0.0, 0
    for c in calls:
        p = prices.get(c.get("model"))
        if p is None:
            unpriced += 1
            continue
        usd += (c.get("input_tokens", 0) * p["input"] + c.get("output_tokens", 0) * p["output"]) / 1e6
    return usd, unpriced


def pick(jobs: dict, per_persona: int, seed: int = 11) -> list[tuple[str, str]]:
    rng, out = random.Random(seed), []
    for persona, cat in CATEGORY.items():
        pool = sorted(j["id"] for j in jobs.values() if j["_truth"]["category"] == cat)
        out += [(persona, j) for j in rng.sample(pool, per_persona)]
    return out


def measure(s: dict, seconds: float) -> dict:
    trace = s.get("trace", [])
    start = datetime.fromisoformat(trace[0]["at"]) if trace else None
    decide = next((t for t in trace if t["node"] == "decide"), None)
    analyze_s = ((datetime.fromisoformat(decide["at"]) - start).total_seconds()
                 + decide["ms"] / 1000) if decide else None
    llm = [c for t in trace for c in t.get("calls", []) if c.get("kind") == "llm"]
    early = [c for t in trace if t["node"] in ANALYSIS for c in t.get("calls", [])
             if c.get("kind") == "llm"]
    total_usd, unpriced = cost(llm)
    return {"status": s.get("status"), "analyze_seconds": round(analyze_s, 2) if analyze_s else None,
            "seconds": round(seconds, 2), "tokens": (s.get("usage") or {}).get("tokens", 0),
            "analyze_usd": round(cost(early)[0], 6), "usd": round(total_usd, 6),
            "unpriced_calls": unpriced, "models": sorted({c.get("model") or "?" for c in llm}),
            "attention": (s.get("attention") or "")[:200]}


def pct(values: list[float], q: float) -> float | None:
    v = sorted(x for x in values if x is not None)
    return v[min(len(v) - 1, int(len(v) * q))] if v else None


def summary(rows: list[dict]) -> dict:
    t = load_config()["targets"]
    drafted = [r for r in rows if r["status"] == "awaiting_approval"]
    stopped = [r for r in rows if r["status"] in ("watching", "skipped")]
    analyze = {"jobs": len(rows), "p50_seconds": pct([r["analyze_seconds"] for r in rows], .5),
               "p95_seconds": pct([r["analyze_seconds"] for r in rows], .95),
               "mean_usd": round(statistics.mean(r["analyze_usd"] for r in rows), 5)}
    proposal = {"jobs": len(drafted), "p50_seconds": pct([r["seconds"] for r in drafted], .5),
                "p95_seconds": pct([r["seconds"] for r in drafted], .95),
                "mean_usd": round(statistics.mean(r["usd"] for r in drafted), 5) if drafted else None}
    # Without the early stop every analysed job would also pay the drafting half.
    draft_half = (statistics.mean(r["usd"] - r["analyze_usd"] for r in drafted)
                  if drafted else 0)
    spent = sum(r["usd"] for r in rows)
    return {
        "analyzed_job": {**analyze, "target_p95_seconds": t["p95_analyze_seconds"],
                         "target_usd": t["usd_per_analyzed_job"],
                         "within": (analyze["p95_seconds"] or 0) <= t["p95_analyze_seconds"]
                         and analyze["mean_usd"] <= t["usd_per_analyzed_job"]},
        "drafted_proposal": {**proposal, "target_p95_seconds": t["p95_proposal_seconds"],
                             "target_usd": t["usd_per_proposal"],
                             "within": bool(drafted) and proposal["p95_seconds"]
                             <= t["p95_proposal_seconds"] and proposal["mean_usd"]
                             <= t["usd_per_proposal"]},
        "early_skip": {"stopped_after_decision": len(stopped), "spent_usd": round(spent, 5),
                       "without_early_skip_usd": round(spent + len(stopped) * draft_half, 5)},
        "errors": sum(r["status"] not in ("awaiting_approval", "watching", "skipped")
                      for r in rows),
        "unpriced_calls": sum(r["unpriced_calls"] for r in rows),
    }


def table(s: dict) -> str:
    a, p, e = s["analyzed_job"], s["drafted_proposal"], s["early_skip"]
    saved = 1 - e["spent_usd"] / e["without_early_skip_usd"] if e["without_early_skip_usd"] else 0
    return "\n".join([
        ("| Unit | Jobs | p50 (s) | p95 (s) | Target p95 (s) | Mean cost (USD) | Target (USD) "
        "| Within budget |"), "| --- | --- | --- | --- | --- | --- | --- | --- |",
        (f"| Analysed job | {a['jobs']} | {a['p50_seconds']} | {a['p95_seconds']} "
        f"| {a['target_p95_seconds']} | {a['mean_usd']} | {a['target_usd']} | {a['within']} |"),
        (f"| Drafted proposal | {p['jobs']} | {p['p50_seconds']} | {p['p95_seconds']} "
        f"| {p['target_p95_seconds']} | {p['mean_usd']} | {p['target_usd']} | {p['within']} |"),
        "", (f"Early skip: {e['stopped_after_decision']} of {a['jobs']} jobs stopped after the "
        f"decision. Spend {e['spent_usd']} USD against {e['without_early_skip_usd']} USD if "
        f"every job were drafted ({saved:.0%} saved). Errors: {s['errors']}. Unpriced (NIM) "
        f"calls: {s['unpriced_calls']}."), ""])


async def run(per_persona: int) -> dict:
    os.environ["GIGSIM_DATA"] = "real"
    os.environ.setdefault("GIGBID_PROFILE", "cerebras")
    load_config()
    app = gigsim_app()
    graph = bid_graph.build(InMemorySaver(serde=serde()))
    toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp})
    rows = []
    for persona, job_id in pick(app.state.data["jobs"], per_persona):
        as_persona(persona)
        cfg = {"configurable": {"thread_id": f"budget-{persona}-{job_id}"}}
        start = time.perf_counter()
        try:
            await graph.ainvoke({"job_id": job_id}, cfg, context=common.Context(toolbox=toolbox))
            row = measure((await graph.aget_state(cfg)).values, time.perf_counter() - start)
        except Exception as e:  # noqa: BLE001 - one bad job must not end the run
            row = {"status": "error", "analyze_seconds": None, "seconds": 0, "tokens": 0,
                   "analyze_usd": 0.0, "usd": 0.0, "unpriced_calls": 0, "models": [],
                   "attention": f"{type(e).__name__}: {e}"[:200]}
        row.update(persona=persona, job_id=job_id)
        print(persona, job_id, row["status"], row["analyze_seconds"], row["seconds"],
              row["usd"], row["attention"][:80], flush=True)
        rows.append(row)
    (RESULTS / "budget_rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return {"profile": profile_name(), "data": "real (held-out)", "summary": summary(rows),
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-persona", type=int, default=8)
    args = parser.parse_args()
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    result = asyncio.run(run(args.per_persona), loop_factory=loop)
    (RESULTS / "budget_eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (RESULTS / "budget_eval.md").write_text(table(result["summary"]), encoding="utf-8")
    print(table(result["summary"]))


if __name__ == "__main__":
    main()
