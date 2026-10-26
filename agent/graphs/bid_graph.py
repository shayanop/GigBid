"""Bid graph (C1): one thread per job.

scout -> analyst | risk | matcher (parallel via Send) -> decide
  skip / watch -> END
  bid -> pricing -> writer -> verifier -> critic --revise (max 2)--> writer
                                          critic -> compliance --block--> END (needs attention)
                                          compliance -> approval (interrupt)
  approval: approve -> submit -> END | edit -> compliance | reject -> END
A node that still fails after retries goes to dead_letter (needs attention).
"""

import asyncio
import difflib
import hashlib
import json
import re
from datetime import UTC, datetime

from langgraph.config import get_config
from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, Send, interrupt

from agent.config import load_config
from agent.handoffs import Approval, BidDecision
from agent.marketplace_port import Proposal
from agent.mcp_client import ToolCallError
from agent.memory.promotion_rules import observe_edit
from agent.memory.store import outcome_notes
from agent.nodes import (
    analyst,
    common,
    compliance,
    critic,
    matcher,
    pricing,
    risk,
    scout,
    verifier,
    writer,
)
from agent.state import BidState

PARALLEL = ("analyst", "risk", "matcher")


@common.node("decide")
async def decide(state: dict) -> dict:
    if state.get("status") == "needs_attention":
        return {}
    rules, risk_, fit = load_config()["decision"], state["risk"], state["fit"]
    if risk_.score > rules["bid_max_risk"]:
        action = "skip"
        reasons = [(f"risk {risk_.score:.2f} above {rules['bid_max_risk']}: "
                   f"{', '.join(risk_.flags) or risk_.summary}")]
    elif fit.score < rules["watch_min_fit"]:
        action, reasons = "skip", [f"fit {fit.score:.2f} below {rules['watch_min_fit']}"]
    elif fit.score < rules["bid_min_fit"]:
        action, reasons = "watch", [(f"fit {fit.score:.2f} below bid threshold "
                                    f"{rules['bid_min_fit']}")]
    else:
        action, reasons = "bid", [f"fit {fit.score:.2f}, risk {risk_.score:.2f}", *fit.reasons]
    store, user = common.memory()
    if store:  # what happened to your past proposals for these skills
        reasons += await outcome_notes(store, user, state["job"].skills)
    status = {"bid": "drafting", "watch": "watching", "skip": "skipped"}[action]
    return {"decision": BidDecision(action=action, reasons=reasons), "status": status}


def _thread_id() -> str:
    return get_config()["configurable"]["thread_id"]


# Evidence citations like "[fr_ml-p09#0]" or "([a#0], [b#1])" are for the freelancer's
# review only; the client never sees them.
CITATION = re.compile(r"\s*\(?\[[\w./-]+#\d+\](?:\s*,\s*\[[\w./-]+#\d+\])*\)?")


def client_text(text: str) -> str:
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", CITATION.sub("", text)).strip()


def _proposal_args(state: dict) -> dict:
    draft = state["draft"]
    return {"job_id": state["job"].id, "cover_letter": client_text(draft.cover_letter),
            "bid_amount": state["price"].amount,
            "screening_answers": [f"{a.question}\n{client_text(a.answer)}"
                                  for a in draft.screening_answers]}


def _key(kind: str, args: dict) -> str:
    """Deterministic idempotency key: a re-run of the same write reuses it."""
    digest = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
    return f"{_thread_id()}:{kind}:{digest}"


@common.node("approval")
async def request_approval(state: dict) -> dict:
    args = _proposal_args(state)
    preview = await common.toolbox().call("approval", "marketplace", "create_proposal_draft",
                                          {**args, "idempotency_key": _key("preview", args),
                                           "dry_run": True})
    by_id = {e.id: e for e in state["evidence"]}
    claims = [{**c.model_dump(), "evidence": [
                  by_id[i].model_dump(mode="json", include={"id", "type", "source", "text"})
                  for i in c.evidence_ids if i in by_id]}
              for c in state["claims"].claims]  # incl. removed ones, so the UI can say so
    decision = Approval.model_validate(interrupt({
        "kind": "proposal_approval", "draft": state["draft"].model_dump(), "claims": claims,
        "risk": state["risk"].model_dump(), "price": state["price"].model_dump(),
        "compliance": state["compliance"].model_dump(), "preview": preview}))
    update = {"approval": decision, "preview": preview}
    if decision.action == "reject":
        return {**update, "status": "rejected", "rejection": decision.reason}
    if decision.action == "edit":
        before = state["draft"].cover_letter
        store, user = common.memory()
        if store:
            await observe_edit(store, user, before, decision.text, f"proposal:{_thread_id()}")
        diff = "".join(difflib.unified_diff(before.splitlines(True),
                                            decision.text.splitlines(True), "draft", "edited"))
        return {**update, "status": "drafting",
                "draft": state["draft"].model_copy(update={"cover_letter": decision.text}),
                "edits": [{"at": datetime.now(UTC).isoformat(), "before": before,
                           "after": decision.text, "diff": diff}]}
    return update


@common.node("submit")
async def submit(state: dict) -> dict:
    args, tools = _proposal_args(state), common.toolbox()
    created = await tools.call("submit", "marketplace", "create_proposal_draft",
                               {**args, "idempotency_key": _key("draft", args)})
    pid = created["proposal"]["id"]
    done = await tools.call("submit", "marketplace", "submit_proposal",
                            {"proposal_id": pid, "idempotency_key": f"{_thread_id()}:submit:{pid}"})
    return {"submission": Proposal.model_validate(done["proposal"]), "status": "submitted"}


async def dead_letter(state: dict, error: NodeError) -> Command:
    reason = f"{error.node} failed: {type(error.error).__name__}: {error.error}"
    return Command(update={"status": "needs_attention", "attention": reason[:500]}, goto=END)


def _retryable(e: Exception) -> bool:
    # Refusals and bad data repeat identically on retry; outages and bad model output may not.
    return not isinstance(e, PermissionError | ToolCallError | ValueError | TypeError | KeyError)


def _contained(name: str, fn):
    """Same retries as the graph default, but a final failure becomes needs_attention
    instead of an exception. LangGraph 1.2 skips error_handler when another task runs in
    the same step, so the parallel branches catch their own failures and time themselves
    out (LangGraph's node timeout would fire outside this wrapper)."""
    async def run(state: dict) -> dict:
        budgets = load_config()["budgets"]
        delay = budgets["retry_initial_seconds"]
        for attempt in range(3):
            try:
                async with asyncio.timeout(budgets["node_timeout_seconds"]):
                    return await fn(state)
            except Exception as e:  # noqa: BLE001 - any failure must end as needs_attention
                if not _retryable(e) or attempt == 2:
                    reason = f"{name} failed: {type(e).__name__}: {e}"
                    return {"status": "needs_attention", "attention": reason[:500]}
                await asyncio.sleep(delay * 2**attempt)
    return run


def _then(nxt: str):
    return lambda s: END if s.get("status") == "needs_attention" else nxt


def _fan_out(state: dict):
    if state.get("status") == "needs_attention":
        return END
    return [Send(name, state) for name in PARALLEL]


def _after_critic(state: dict) -> str:
    if state.get("status") == "needs_attention":
        return END
    max_rewrites = load_config()["critic"]["max_revisions"]
    if not state["critique"].approve and state.get("revisions", 0) < max_rewrites:
        return "writer"
    return "compliance"


def _after_approval(state: dict) -> str:
    if state.get("status") in ("needs_attention", "rejected"):
        return END
    return "compliance" if state["approval"].action == "edit" else "submit"


def build(checkpointer=None, store=None):
    budgets = load_config()["budgets"]
    g = StateGraph(BidState, context_schema=common.Context)
    g.set_node_defaults(
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=budgets["retry_initial_seconds"],
                                 retry_on=_retryable),
        timeout=budgets["node_timeout_seconds"], error_handler=dead_letter)
    for name, fn in [("scout", scout.load_job), ("analyst", analyst.analyze),
                     ("risk", risk.assess), ("matcher", matcher.match), ("decide", decide),
                     ("pricing", pricing.quote), ("writer", writer.write),
                     ("verifier", verifier.verify), ("critic", critic.review),
                     ("compliance", compliance.check), ("approval", request_approval),
                     ("submit", submit)]:
        if name in PARALLEL:  # own retries and timeout; the outer cap is only a backstop
            g.add_node(name, _contained(name, fn), retry_policy=RetryPolicy(max_attempts=1),
                       timeout=budgets["node_timeout_seconds"] * 4)
        else:
            g.add_node(name, fn)
    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", _fan_out, [*PARALLEL, END])
    for name in PARALLEL:
        g.add_edge(name, "decide")
    g.add_conditional_edges("decide", lambda s: "pricing" if s.get("status") == "drafting"
                            else END, ["pricing", END])
    for a, b in [("pricing", "writer"), ("writer", "verifier"), ("verifier", "critic")]:
        g.add_conditional_edges(a, _then(b), [b, END])
    g.add_conditional_edges("critic", _after_critic, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", lambda s: "approval"
                            if s.get("status") == "awaiting_approval" else END, ["approval", END])
    g.add_conditional_edges("approval", _after_approval, ["submit", "compliance", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store)


async def _demo(job_id: str) -> None:
    """Dev smoke run with real models; GigSim and both MCP servers run in this process.
    Users come from MARKETPLACE_LOCAL_USER / PORTFOLIO_LOCAL_USER. Stops at approval."""
    import httpx
    from langgraph.checkpoint.memory import InMemorySaver

    from agent.graphs.checkpoint import serde
    from agent.mcp_client import Toolbox
    from gigsim.app import create_app
    from mcp_servers.marketplace import server as marketplace
    from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
    from mcp_servers.portfolio import server as portfolio

    gigsim = create_app()
    marketplace.adapter_for = lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.ASGITransport(app=gigsim))
    cfg = {"configurable": {"thread_id": f"demo-{job_id}"}}
    graph = build(InMemorySaver(serde=serde()))
    toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp})
    await graph.ainvoke({"job_id": job_id}, cfg, context=common.Context(toolbox=toolbox))
    s = (await graph.aget_state(cfg)).values
    for key in ("status", "attention", "decision", "risk", "fit", "price", "claims", "critique",
                "compliance", "usage"):
        if key in s:
            value = s[key]
            print(f"--- {key}")
            print(value.model_dump_json(indent=1) if hasattr(value, "model_dump_json") else value)
    if "draft" in s:
        print(f"--- draft ({s.get('revisions', 0)} revisions)")
        print(s["draft"].cover_letter)


if __name__ == "__main__":
    import asyncio
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # model output has non-ASCII; Windows consoles
    asyncio.run(_demo(sys.argv[1]))
