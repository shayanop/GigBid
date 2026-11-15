"""Decision eval (E2): bid/skip F1, scam precision and recall, and the share of prices inside
the fair band, on a fixed sample of development jobs.

Labels come from GigSim's hidden truth, not from the agent: a job is a "bid" for a persona
when it is in that persona's category, is not a scam and is not a repost. Every dev job's
skills are covered by its persona's portfolio (evals/datasets/persona_truth.json), so the
rule needs no fit threshold. "Watch" counts as not bidding.

The graph runs with real models up to the writer, so a job costs about 6k tokens (bid jobs
also price). Rows are appended to evals/results/decision_rows.jsonl as they finish, and a
rerun skips the finished ones: a rate limit costs a wait, not the run (--fresh restarts).

Run: GIGBID_PROFILE=cerebras uv run python -m evals.runners.decision_eval [--per-persona 20]
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from datetime import UTC, datetime

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import load_config, profile_name
from agent.graphs import bid_graph
from agent.graphs.checkpoint import serde
from agent.mcp_client import Toolbox
from agent.nodes import common
from evals.runners.rag_eval import RESULTS
from gigsim.app import create_app
from mcp_servers.marketplace import server as marketplace
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.portfolio import server as portfolio

CATEGORY = {"fr_ml": "ml", "fr_fs": "fullstack", "fr_da": "data"}
ROWS = RESULTS / "decision_rows.jsonl"


def label(job: dict, persona: str) -> str:
    t = job["_truth"]
    return "bid" if (t["category"] == CATEGORY[persona] and not t["scam"]
                     and not t["duplicate_of"]) else "skip"


def sample(jobs: dict, per_persona: int, seed: int = 7) -> list[tuple[str, str]]:
    """(persona, job_id) pairs: 60% clean jobs in the persona's niche, 20% scams in it,
    20% clean jobs from other niches. Fixed by the seed, so every variant sees the same jobs."""
    rng, out = random.Random(seed), []
    pool = [j for j in jobs.values() if not j["_truth"]["duplicate_of"]
            and not j["_truth"]["injection"]]
    for persona, cat in CATEGORY.items():
        clean = sorted(j["id"] for j in pool if j["_truth"]["category"] == cat
                       and not j["_truth"]["scam"])
        scams = sorted(j["id"] for j in pool if j["_truth"]["category"] == cat
                       and j["_truth"]["scam"])
        other = sorted(j["id"] for j in pool if j["_truth"]["category"] != cat
                       and not j["_truth"]["scam"])
        n_scam = n_other = per_persona // 5
        picks = (rng.sample(clean, per_persona - n_scam - n_other) + rng.sample(scams, n_scam)
                 + rng.sample(other, n_other))
        out += [(persona, j) for j in picks]
    return out


def gigsim_app():
    app = create_app()
    marketplace.adapter_for = lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.ASGITransport(app=app))
    return app


def as_persona(persona: str) -> None:
    """The in-process MCP servers read the user per call from these (mcp_servers/auth.py)."""
    os.environ["MARKETPLACE_LOCAL_USER"] = os.environ["PORTFOLIO_LOCAL_USER"] = persona


async def run_job(graph, toolbox, persona: str, job_id: str) -> dict:
    as_persona(persona)
    cfg = {"configurable": {"thread_id": f"decision-{persona}-{job_id}"}}
    start = time.perf_counter()
    await graph.ainvoke({"job_id": job_id}, cfg, context=common.Context(toolbox=toolbox),
                        interrupt_before=["writer"])
    s = (await graph.aget_state(cfg)).values
    decision = s.get("decision")
    return {"persona": persona, "job_id": job_id,
            "action": decision.action if decision else "error",
            "risk": s["risk"].score if s.get("risk") else None,
            "flags": s["risk"].flags if s.get("risk") else [],
            "fit": s["fit"].score if s.get("fit") else None,
            "price": s["price"].amount if s.get("price") else None,
            "tokens": (s.get("usage") or {}).get("tokens", 0),
            "seconds": round(time.perf_counter() - start, 2),
            "attention": (s.get("attention") or "")[:300]}


def scores(rows: list[dict], jobs: dict) -> dict:
    """Bid/skip F1 with "bid" as the positive class; errors count as not bidding."""
    ok = [r for r in rows if r["action"] != "error"]
    tp = sum(r["label"] == "bid" and r["action"] == "bid" for r in rows)
    fp = sum(r["label"] == "skip" and r["action"] == "bid" for r in rows)
    fn = sum(r["label"] == "bid" and r["action"] != "bid" for r in rows)
    precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    scam = [jobs[r["job_id"]]["_truth"]["scam"] for r in ok]
    flagged = [r["risk"] is not None and r["risk"] > load_config()["decision"]["bid_max_risk"]
               for r in ok]
    s_tp = sum(a and b for a, b in zip(scam, flagged, strict=True))
    priced = [r for r in ok if r["price"] is not None]
    in_band = [lo <= r["price"] <= hi for r in priced
               for lo, hi in [jobs[r["job_id"]]["_truth"]["fair_band"]]]
    secs = sorted(r["seconds"] for r in ok)
    confusion = {lab: {act: sum(r["label"] == lab and r["action"] == act for r in rows)
                       for act in ("bid", "watch", "skip", "error")} for lab in ("bid", "skip")}
    return {
        "jobs": len(rows), "errors": len(rows) - len(ok),
        "bid_precision": round(precision, 3), "bid_recall": round(recall, 3),
        "bid_f1": round(2 * precision * recall / max(precision + recall, 1e-9), 3),
        "accuracy": round(sum((r["action"] == "bid") == (r["label"] == "bid") for r in rows)
                          / max(len(rows), 1), 3),
        "confusion": confusion,
        "scam_precision": round(s_tp / max(sum(flagged), 1), 3),
        "scam_recall": round(s_tp / max(sum(scam), 1), 3),
        "price_in_fair_band": round(sum(in_band) / len(in_band), 3) if in_band else None,
        "tokens_per_job": round(statistics.mean(r["tokens"] for r in ok)) if ok else 0,
        "p50_seconds": secs[len(secs) // 2] if secs else None,
        "p95_seconds": secs[min(len(secs) - 1, int(len(secs) * 0.95))] if secs else None,
    }


def table(result: dict) -> str:
    s = result["scores"]
    c = s["confusion"]
    return "\n".join([
        ("| Jobs | Bid F1 | Bid precision | Bid recall | Accuracy | Scam precision | Scam recall "
        "| Price in fair band | Tokens per job | p95 (s) | Errors |"),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        (f"| {s['jobs']} | {s['bid_f1']} | {s['bid_precision']} | {s['bid_recall']} "
        f"| {s['accuracy']} | {s['scam_precision']} | {s['scam_recall']} "
        f"| {s['price_in_fair_band']} | {s['tokens_per_job']} | {s['p95_seconds']} "
        f"| {s['errors']} |"),
        "",
        "| Label | Agent bid | Agent watch | Agent skip | Error |",
        "| --- | --- | --- | --- | --- |",
        *[f"| {lab} | {c[lab]['bid']} | {c[lab]['watch']} | {c[lab]['skip']} | {c[lab]['error']} |"
          for lab in ("bid", "skip")], ""])


async def run(per_persona: int, fresh: bool) -> dict:
    gigsim = gigsim_app()
    jobs = gigsim.state.data["jobs"]
    done = {} if fresh or not ROWS.exists() else {
        (r["persona"], r["job_id"]): r
        for r in map(json.loads, ROWS.read_text(encoding="utf-8").splitlines())
        if r["action"] != "error"}  # errored rows are retried
    if fresh:
        ROWS.unlink(missing_ok=True)
    graph = bid_graph.build(InMemorySaver(serde=serde()))
    toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp})
    rows = []
    for persona, job_id in sample(jobs, per_persona):
        if (persona, job_id) in done:
            rows.append(done[(persona, job_id)])
            continue
        try:
            row = await run_job(graph, toolbox, persona, job_id)
        except Exception as e:  # noqa: BLE001 - one bad job must not end the run
            row = {"persona": persona, "job_id": job_id, "action": "error", "risk": None,
                   "flags": [], "fit": None, "price": None, "tokens": 0, "seconds": 0,
                   "attention": f"{type(e).__name__}: {e}"[:300]}
        row["label"] = label(jobs[job_id], persona)
        print(f"{persona} {job_id} label={row['label']} action={row['action']} "
              f"fit={row['fit']} risk={row['risk']} {row['attention'][:80]}", flush=True)
        with ROWS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        rows.append(row)
    return {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "profile": profile_name(), "per_persona": per_persona,
            "scores": scores(rows, jobs), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-persona", type=int, default=20)
    parser.add_argument("--fresh", action="store_true", help="ignore rows from earlier runs")
    args = parser.parse_args()
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    result = asyncio.run(run(args.per_persona, args.fresh), loop_factory=loop)
    (RESULTS / "decision_eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (RESULTS / "decision_eval.md").write_text(table(result), encoding="utf-8")
    print(table(result))


if __name__ == "__main__":
    main()
