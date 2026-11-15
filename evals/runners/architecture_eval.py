"""Architecture experiment (C8): is the hand-built graph worth it? The same development jobs
run through three implementations on the same model (gpt-oss-120b on Cerebras), so only the
architecture differs:

1. react: one ReAct agent with every read-only marketplace and portfolio tool.
2. supervisor: a prebuilt langgraph-supervisor with researcher, matcher and writer agents.
3. custom: the bid graph (agent/graphs/bid_graph.py) under GIGBID_PROFILE=c8.

Every output is scored the same way after the run, outside its token count:
- bid/skip accuracy against GigSim's truth (evals/runners/decision_eval.label);
- unsupported claims: the Claim Verifier on the final letter, against the evidence that
  implementation retrieved (citing an id it never saw is unsupported);
- compliance violations: the Compliance Guard on the final letter;
- GigSim reply rate: each bid is submitted to that implementation's own GigSim copy, whose
  rule-based client replies or not. This is the simulator only; nothing leaves GigBid.

All three share Cerebras' free quota (1M tokens and 2,400 requests a day, 150 an hour), and
the full run needs about 4M tokens. So the jobs are interleaved (each job through all three
before the next), rows go to evals/results/architecture_rows.jsonl as they finish, and a
rerun skips finished ones. Three errors in a row mean the quota is spent: the run stops,
and with --wait it retries every hour until every row is done (--fresh restarts).

Run: uv run python -m evals.runners.architecture_eval [--jobs 50] [--only react] [--wait]
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from typing import Literal

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent import mcp_client
from agent.config import _cerebras_pace, load_config
from agent.graphs import bid_graph
from agent.graphs.checkpoint import serde
from agent.handoffs import ProposalDraft, ScreeningAnswer
from agent.mcp_client import Toolbox
from agent.nodes import common, compliance
from agent.nodes.verifier import check_claims
from evals.runners.decision_eval import as_persona, gigsim_app, label, sample
from evals.runners.rag_eval import RESULTS
from mcp_servers.marketplace import server as marketplace
from mcp_servers.portfolio import server as portfolio
from rag.schema import Evidence

ROWS = RESULTS / "architecture_rows.jsonl"
MODEL = "gpt-oss-120b"  # Cerebras, as in the c8 profile
FILLED = "Happy to agree this on a short call."  # stands in for the freelancer's own answer
READ_TOOLS = {"marketplace": ["get_job", "get_client_history", "search_jobs",
                              "get_connects_balance"],
              "portfolio": ["search_evidence", "get_case_study", "list_skills"]}
WRITER_RULES = common.prompt("writer")[1]


class Outcome(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reasons: list[str]
    bid_amount: float = Field(description="USD, per hour for hourly jobs; 0 unless bidding")
    cover_letter: str = Field(description="The full proposal text if bidding, else empty")
    screening_answers: list[ScreeningAnswer] = Field(
        description="One answer per screening question if bidding, else empty")


TASK = f"""You are a freelancer's bidding copilot. For the job id you are given:
1. Read the job and the client's history. Skip scams and clients you would not trust.
2. Search the freelancer's portfolio for evidence for each requirement.
3. Decide: bid if the portfolio shows the required work and the client is trustworthy,
   watch if the fit is partial, skip otherwise.
4. If you bid, price it (USD; hourly jobs per hour) and write the proposal.
Cite only evidence ids returned by search_evidence. Never submit anything.

Proposal rules:
{WRITER_RULES}"""


def llm():
    from langchain_cerebras import ChatCerebras
    return ChatCerebras(model=MODEL, temperature=0, rate_limiter=_cerebras_pace())


def tools(toolbox: Toolbox, seen: dict, names: dict = READ_TOOLS) -> list[StructuredTool]:
    """MCP tools as LangChain tools, through the same Toolbox and allowlist as the graph."""
    mcp_client.ALLOWLIST["baseline"] = {(s, t) for s, ts in READ_TOOLS.items() for t in ts}
    def make(server: str, spec) -> StructuredTool:
        async def call(**kwargs):
            try:
                out = await toolbox.call("baseline", server, spec.name, kwargs)
            except Exception as e:  # noqa: BLE001 - the agent sees the error and can recover
                return f"error: {e}"
            if spec.name == "search_evidence":
                seen.update({e["id"]: Evidence.model_validate(e) for e in out})
            return json.dumps(out, default=str)[:6000]
        return StructuredTool(name=spec.name, description=spec.description or spec.name,
                              args_schema=spec.input_schema, coroutine=call)
    return [make(server, spec) for server, specs in TOOL_SPECS.items() for spec in specs
            if spec.name in names.get(server, [])]


TOOL_SPECS: dict = {}


async def load_specs() -> None:
    TOOL_SPECS.update({"marketplace": await marketplace.mcp.list_tools(),
                       "portfolio": await portfolio.mcp.list_tools()})


def react(toolbox, seen):
    return create_react_agent(llm(), tools(toolbox, seen), prompt=TASK, response_format=Outcome)


def supervisor(toolbox, seen):
    from langgraph_supervisor import create_supervisor
    model = llm()
    workers = [
        create_react_agent(model, tools(toolbox, seen, {"marketplace": [
            "get_job", "get_client_history", "get_connects_balance"]}), name="researcher",
            prompt="Read the job and the client's history and report requirements, budget, "
                   "screening questions and any scam signals."),
        create_react_agent(model, tools(toolbox, seen, {"portfolio": [
            "search_evidence", "list_skills"]}), name="matcher",
            prompt="Search the portfolio for evidence for each requirement you are given. "
                   "Report the evidence ids and what each shows."),
        create_react_agent(model, tools(toolbox, seen, {"portfolio": [
            "search_evidence", "get_case_study"]}), name="writer",
            prompt="Write the proposal from the job details and evidence you are given.\n\n"
                   + WRITER_RULES),
    ]
    return create_supervisor(workers, model=model, response_format=Outcome,
                             prompt=TASK + "\n\nDelegate: researcher first, then matcher, "
                             "then writer only if you bid.").compile()


async def run_baseline(kind: str, toolbox, job_id: str) -> tuple[Outcome | None, list, dict]:
    seen: dict = {}
    agent = (react if kind == "react" else supervisor)(toolbox, seen)
    with get_usage_metadata_callback() as usage:
        out = await agent.ainvoke({"messages": [{"role": "user", "content": f"Job id: {job_id}"}]},
                                  {"recursion_limit": 40})
        outcome = out.get("structured_response")
        if outcome is None:  # langgraph-supervisor returned only messages: extract, as ReAct does
            outcome = await llm().with_structured_output(Outcome).ainvoke(
                [*out["messages"], {"role": "user", "content": "Return your final decision, "
                                    "price and proposal in the required format."}])
    tokens = sum(u.get("total_tokens", 0) for u in usage.usage_metadata.values())
    return outcome, list(seen.values()), {"tokens": tokens}


async def run_custom(graph, toolbox, persona: str, job_id: str):
    cfg = {"configurable": {"thread_id": f"c8-{persona}-{job_id}"}}
    await graph.ainvoke({"job_id": job_id}, cfg, context=common.Context(toolbox=toolbox))
    s = (await graph.aget_state(cfg)).values
    decision = s.get("decision")
    draft = s.get("draft") if s.get("status") == "awaiting_approval" else None
    outcome = Outcome(action=decision.action if decision else "skip",
                      reasons=decision.reasons if decision else [s.get("attention") or ""],
                      bid_amount=s["price"].amount if s.get("price") else 0,
                      cover_letter=draft.cover_letter if draft else "",
                      screening_answers=draft.screening_answers if draft else [])
    return outcome, s.get("evidence", []), {"tokens": (s.get("usage") or {}).get("tokens", 0),
                                            "cfg": cfg, "status": s.get("status"),
                                            "attention": (s.get("attention") or "")[:200]}


async def submit(kind: str, app, toolbox, graph, persona: str, job_id: str, o: Outcome,
                 meta: dict) -> bool:
    """Submits the bid to this implementation's GigSim copy; True if the client replied."""
    threads = app.state.data["threads"]
    before = {tid for tid, t in threads.items() if t["job_id"] == job_id}
    answers = [a.model_copy(update={"answer": FILLED}) if bid_graph.TO_CONFIRM in a.answer
               else a for a in o.screening_answers]
    if kind == "custom":
        ctx = common.Context(toolbox=toolbox)
        if answers != o.screening_answers:
            await graph.ainvoke(Command(resume={"action": "edit", "text": o.cover_letter,
                                                "answers": [a.answer for a in answers]}),
                                meta["cfg"], context=ctx)
        await graph.ainvoke(Command(resume={"action": "approve"}), meta["cfg"], context=ctx)
        if (await graph.aget_state(meta["cfg"])).values.get("status") != "submitted":
            return False
    else:
        args = {"job_id": job_id, "cover_letter": bid_graph.client_text(o.cover_letter),
                "bid_amount": o.bid_amount or 0,
                "screening_answers": [f"{a.question}\n{bid_graph.client_text(a.answer)}"
                                      for a in answers]}
        created = await toolbox.call("submit", "marketplace", "create_proposal_draft",
                                     {**args, "idempotency_key": f"c8-{kind}-{job_id}"})
        pid = created["proposal"]["id"]
        await toolbox.call("submit", "marketplace", "submit_proposal",
                           {"proposal_id": pid, "idempotency_key": f"c8-{kind}-{pid}"})
    return any(t["job_id"] == job_id and t["freelancer_id"] == persona and tid not in before
               for tid, t in threads.items())


async def score_letter(o: Outcome, evidence: list) -> dict:
    """Verifier and Compliance Guard on the final letter, outside the run's token count."""
    draft = ProposalDraft(cover_letter=o.cover_letter, screening_answers=o.screening_answers)
    claims = await check_claims(draft, evidence)
    verdict = (await compliance.check({"draft": draft, "claims": claims}))["compliance"]
    return {"claims": len(claims.claims), "unsupported": len(claims.unsupported),
            "violations": verdict.violations, "compliance": verdict.status}


async def one(kind, app, toolbox, graph, persona, job_id) -> dict:
    as_persona(persona)
    start = time.perf_counter()
    if kind == "custom":
        o, evidence, meta = await run_custom(graph, toolbox, persona, job_id)
    else:
        o, evidence, meta = await run_baseline(kind, toolbox, job_id)
    row = {"impl": kind, "persona": persona, "job_id": job_id,
           "action": o.action if o else "error", "tokens": meta["tokens"],
           "seconds": round(time.perf_counter() - start, 1),
           "bid_amount": o.bid_amount if o else None, "letter": o.cover_letter if o else "",
           "status": meta.get("status"),  # the custom graph's own end state, and why
           "attention": meta.get("attention")}
    if o and o.action == "bid":
        row["empty_letter"] = not o.cover_letter.strip()  # decided to bid, wrote nothing
        if not row["empty_letter"]:
            row.update(await score_letter(o, evidence))
            try:
                row["replied"] = await submit(kind, app, toolbox, graph, persona, job_id, o, meta)
            except mcp_client.ToolCallError as e:  # e.g. a bid with no price: GigSim refuses it
                row["replied"], row["submit_error"] = False, str(e)[:200]
    return row


def summary(rows: list[dict]) -> dict:
    out = {}
    for kind in ("react", "supervisor", "custom"):
        rs = [r for r in rows if r["impl"] == kind]
        if not rs:
            continue
        bids = [r for r in rs if "claims" in r]
        secs = sorted(r["seconds"] for r in rs)
        out[kind] = {
            "jobs": len(rs), "errors": sum(r["action"] == "error" for r in rs),
            "accuracy": round(sum((r["action"] == "bid") == (r["label"] == "bid") for r in rs)
                              / len(rs), 3),
            "bids": len(bids), "empty_letters": sum(r.get("empty_letter", False) for r in rs),
            "unsupported_per_proposal": round(statistics.mean(r["unsupported"] for r in bids), 2)
            if bids else None,
            "violations_per_proposal": round(statistics.mean(len(r["violations"]) for r in bids),
                                             2) if bids else None,
            "reply_rate": round(sum(r.get("replied", False) for r in bids) / len(bids), 3)
            if bids else None,
            "tokens_per_job": round(statistics.mean(r["tokens"] for r in rs)),
            "p50_seconds": secs[len(secs) // 2],
            "p95_seconds": secs[min(len(secs) - 1, int(len(secs) * 0.95))],
        }
    return out


def table(s: dict) -> str:
    lines = [("| Implementation | Jobs | Bid/skip accuracy | Bids | Bids with no letter | Unsupported claims per "
             "proposal | Compliance violations per proposal | GigSim reply rate | Tokens per "
             "job | p50 (s) | p95 (s) | Errors |"), "| --- " * 12 + "|"]
    for kind, m in s.items():
        lines.append(f"| {kind} | {m['jobs']} | {m['accuracy']} | {m['bids']} | {m['empty_letters']} "
                     f"| {m['unsupported_per_proposal']} | {m['violations_per_proposal']} "
                     f"| {m['reply_rate']} | {m['tokens_per_job']} | {m['p50_seconds']} "
                     f"| {m['p95_seconds']} | {m['errors']} |")
    return "\n".join(lines) + "\n"


class QuotaSpent(Exception):
    pass


async def run(n_jobs: int, only: list[str], fresh: bool) -> dict:
    os.environ["GIGBID_PROFILE"] = "c8"  # the custom graph on the baselines' model
    load_config()  # loads .env
    await load_specs()
    if fresh:
        ROWS.unlink(missing_ok=True)
    done = {} if not ROWS.exists() else {
        (r["impl"], r["persona"], r["job_id"]): r
        for r in map(json.loads, ROWS.read_text(encoding="utf-8").splitlines())
        if r["action"] != "error"}
    probe = gigsim_app()
    jobs = sample(probe.state.data["jobs"], 17)[:n_jobs]
    # A marketplace per implementation: its own Connects and replies. Each one() call points
    # the Marketplace MCP adapter at that implementation's app.
    envs = {}
    for kind in only:
        app = gigsim_app()
        envs[kind] = (app, marketplace.adapter_for)
    rows, failures, graphs = [], 0, {}
    for persona, job_id in jobs:
        for kind in only:
            if (kind, persona, job_id) in done:
                rows.append(done[(kind, persona, job_id)])
                continue
            app, adapter = envs[kind]
            marketplace.adapter_for = adapter
            toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp})
            graph = graphs.setdefault(kind, bid_graph.build(InMemorySaver(serde=serde())))
            try:
                row = await one(kind, app, toolbox, graph, persona, job_id)
            except Exception as e:  # noqa: BLE001 - one bad job must not end the run
                row = {"impl": kind, "persona": persona, "job_id": job_id, "action": "error",
                       "tokens": 0, "seconds": 0, "error": f"{type(e).__name__}: {e}"[:300]}
            row["label"] = label(probe.state.data["jobs"][job_id], persona)
            print(f"{kind} {persona} {job_id} label={row['label']} action={row['action']} "
                  f"unsupported={row.get('unsupported')} replied={row.get('replied')} "
                  f"tokens={row['tokens']} {row.get('error', '')[:100]}", flush=True)
            with ROWS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            rows.append(row)
            failures = failures + 1 if row["action"] == "error" else 0
            if failures >= 3:
                raise QuotaSpent(row.get("error", ""))
    return {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "model": MODEL,
            "jobs": n_jobs, "summary": summary(rows), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=50)
    parser.add_argument("--only", nargs="+", default=["custom", "react", "supervisor"])
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--wait", action="store_true",
                        help="when the quota runs out, retry every hour until done")
    args = parser.parse_args()
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    fresh = args.fresh
    while True:
        try:
            result = asyncio.run(run(args.jobs, args.only, fresh), loop_factory=loop)
        except QuotaSpent as e:
            print(f"{datetime.now(UTC):%Y-%m-%d %H:%M} quota spent ({str(e)[:120]}); "
                  f"{'retrying in an hour' if args.wait else 'stopping'}", flush=True)
            if not args.wait:
                return
            fresh = False
            time.sleep(3600)
            continue
        if not args.wait or not any(r["action"] == "error" for r in result["rows"]):
            break
        fresh = False
        time.sleep(3600)  # some rows errored without spending the quota: retry them later
    (RESULTS / "architecture_eval.json").write_text(json.dumps(result, indent=1),
                                                    encoding="utf-8")
    (RESULTS / "architecture_eval.md").write_text(table(result["summary"]), encoding="utf-8")
    print(table(result["summary"]))


if __name__ == "__main__":
    main()
