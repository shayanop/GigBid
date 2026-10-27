"""Claim verification (B3): unsupported claims per proposal before and after the verifier.

For each job, the real bid graph (real models, in-process GigSim and MCP servers) runs to
the approval step. "Before" is the verifier's labelling of the writer's first draft;
"after" is an independent re-check of the final draft the human would see. Each run costs
roughly 25k model tokens, so the default sample is small; say so wherever it is quoted.

Run: uv run python -m evals.runners.claims_eval [--jobs 5]
"""

import argparse
import asyncio
import json
import statistics
import sys
from datetime import UTC, datetime

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_config
from langgraph.store.memory import InMemoryStore

from agent.config import load_config
from agent.graphs import bid_graph
from agent.graphs.checkpoint import serde
from agent.handoffs import ClaimReport
from agent.mcp_client import Toolbox
from agent.nodes import common
from agent.nodes.verifier import check_claims
from evals.runners.rag_eval import DATASET, RESULTS
from gigsim.app import create_app
from mcp_servers.marketplace import server as marketplace
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.portfolio import server as portfolio


def _rate(reports) -> dict:
    claims = [len(r.claims) for r in reports]
    unsupported = [len(r.unsupported) for r in reports]
    return {"claims_per_proposal": round(statistics.mean(claims), 2),
            "unsupported_per_proposal": round(statistics.mean(unsupported), 2),
            "unsupported_share": round(sum(unsupported) / max(sum(claims), 1), 3)}


async def run(n_jobs: int) -> dict:
    gigsim = create_app()
    marketplace.adapter_for = lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.ASGITransport(app=gigsim))
    jobs = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    jobs = [j for j in jobs if j["persona"] == "fr_ml"
            and not gigsim.state.data["jobs"][j["job_id"]]["_truth"]["scam"]][:n_jobs]

    first_drafts, original_ask = {}, common.ask

    async def spy(node, schema, user):  # keep the verifier's view of each first draft
        out = await original_ask(node, schema, user)
        thread = get_config()["configurable"]["thread_id"]
        if node == "verifier" and thread not in first_drafts:
            first_drafts[thread] = out
        return out
    common.ask = spy

    graph = bid_graph.build(InMemorySaver(serde=serde()), InMemoryStore())
    toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp})
    rows = []
    for job in jobs:
        cfg = {"configurable": {"thread_id": f"claims-{job['job_id']}"}}
        await graph.ainvoke({"job_id": job["job_id"]}, cfg, context=common.Context(toolbox=toolbox))
        values = (await graph.aget_state(cfg)).values
        if "draft" not in values or cfg["configurable"]["thread_id"] not in first_drafts:
            rows.append({"job_id": job["job_id"], "status": values.get("status"),
                         "attention": values.get("attention")})
            if "RateLimitError" in (values.get("attention") or ""):
                break  # out of model quota; the rest would fail the same way
            continue
        common.ask = original_ask
        try:
            after = await check_claims(values["draft"], values["evidence"])
        except Exception as e:  # noqa: BLE001 - e.g. the provider's daily token cap: keep what we have
            rows.append({"job_id": job["job_id"], "status": f"recheck failed: {type(e).__name__}"})
            break
        finally:
            common.ask = spy
        before = first_drafts[cfg["configurable"]["thread_id"]]
        rows.append({"job_id": job["job_id"], "status": values["status"],
                     "revisions": values.get("revisions", 0),
                     "tokens": (values.get("usage") or {}).get("tokens", 0),
                     "before": before.model_dump(), "after": after.model_dump(),
                     "final_draft": values["draft"].cover_letter})
    common.ask = original_ask
    drafted = [r for r in rows if "before" in r]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "profile": load_config()["profile"], "jobs_attempted": len(rows),
        "proposals_measured": len(drafted),
        "before_verification": _rate([ClaimReport.model_validate(r["before"]) for r in drafted])
        if drafted else None,
        "after_verification": _rate([ClaimReport.model_validate(r["after"]) for r in drafted])
        if drafted else None,
        "tokens_per_proposal": round(statistics.mean(r["tokens"] for r in drafted)) if drafted else 0,
        "per_job": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=5)
    args = parser.parse_args()
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    result = asyncio.run(run(args.jobs), loop_factory=loop)
    (RESULTS / "claims_eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "per_job"}, indent=1))


if __name__ == "__main__":
    main()
