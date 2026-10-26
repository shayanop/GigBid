"""Bid graph state (C2). Keys written by the parallel analyst/risk/matcher branches
are distinct, except the shared trace and usage counters, which use reducers.

Layers: this state holds only the current job; `trace` is the execution trace;
long-term memory lives in the LangGraph store, never here."""

import operator
from typing import Annotated, Literal, TypedDict

from agent.handoffs import (
    Approval,
    BidDecision,
    ClaimReport,
    ComplianceVerdict,
    Critique,
    FitReport,
    JobSpec,
    LiaisonReply,
    MessageIntent,
    PriceQuote,
    ProposalDraft,
    RiskReport,
)
from agent.marketplace_port import Client, Job, Message, Proposal
from rag.schema import Evidence

Status = Literal["analyzing", "skipped", "watching", "drafting", "awaiting_approval",
                 "rejected", "submitted", "needs_attention"]


def add_usage(a: dict | None, b: dict | None) -> dict:
    a, b = a or {}, b or {}
    return {k: a.get(k, 0) + b.get(k, 0) for k in {*a, *b}}


def latest(a, b):
    """Last write wins; lets parallel branches both report status in one step."""
    return b


class TraceEvent(TypedDict):
    node: str
    at: str
    ms: float
    tokens: int
    calls: list[dict]  # tool and model calls made inside the node


class BidState(TypedDict, total=False):
    job_id: str
    job: Job
    client: Client
    spec: JobSpec
    risk: RiskReport
    fit: FitReport
    evidence: list[Evidence]
    decision: BidDecision
    price: PriceQuote
    draft: ProposalDraft
    claims: ClaimReport
    critique: Critique
    revisions: int
    compliance: ComplianceVerdict
    preview: dict  # dry_run payload and Connects cost shown in the approval UI
    approval: Approval
    edits: Annotated[list[dict], operator.add]  # human edit diffs, for style memory
    rejection: str
    submission: Proposal
    status: Annotated[Status, latest]
    attention: Annotated[str, latest]  # why a human must look (block, budget, failure)
    trace: Annotated[list[TraceEvent], operator.add]
    usage: Annotated[dict, add_usage]  # {"steps": n, "tokens": n}


class ConversationState(TypedDict, total=False):
    """One thread per marketplace conversation; each new client message is a new run."""
    conversation_id: str
    message_id: str  # the client message this run answers
    job: Job | None
    messages: list[Message]
    intent: MessageIntent
    slots: list[dict]  # interview times offered in the reply
    reply: LiaisonReply
    compliance: ComplianceVerdict
    preview: dict
    approval: Approval | None
    edits: Annotated[list[dict], operator.add]
    rejection: str | None
    sent: Message | None
    holds: list[dict]
    status: Annotated[str, latest]
    attention: Annotated[str | None, latest]
    trace: Annotated[list[TraceEvent], operator.add]
    usage: Annotated[dict, add_usage]
    budget_base: dict  # usage when this run started; budgets apply per run
