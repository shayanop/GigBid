"""Conversation graph (C1): one thread per marketplace conversation.

read -> classify --interview--> slots -> liaison (draft) -> check --block--> END
                 --otherwise-----------> liaison
check -> approval (interrupt): approve -> send -> END | edit -> check | reject -> END
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agent.config import load_config
from agent.graphs.bid_graph import _retryable, _then, dead_letter
from agent.nodes import common, liaison
from agent.state import ConversationState


def _after_read(state: dict) -> str:
    return END if state.get("status") in ("idle", "needs_attention") else "classify"


def _after_classify(state: dict) -> str:
    if state.get("status") == "needs_attention":
        return END
    return "slots" if state["intent"].intent == "interview" else "liaison"


def _after_approval(state: dict) -> str:
    if state.get("status") in ("needs_attention", "rejected"):
        return END
    return "check" if state["approval"].action == "edit" else "send"


def build(checkpointer=None, store=None):
    budgets = load_config()["budgets"]
    g = StateGraph(ConversationState, context_schema=common.Context)
    g.set_node_defaults(
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=budgets["retry_initial_seconds"],
                                 retry_on=_retryable),
        timeout=budgets["node_timeout_seconds"], error_handler=dead_letter)
    for name, fn in [("read", liaison.read), ("classify", liaison.classify),
                     ("slots", liaison.find_slots), ("liaison", liaison.draft),
                     ("check", liaison.check), ("approval", liaison.request_approval),
                     ("send", liaison.send)]:
        g.add_node(name, fn)
    g.add_edge(START, "read")
    g.add_conditional_edges("read", _after_read, ["classify", END])
    g.add_conditional_edges("classify", _after_classify, ["slots", "liaison", END])
    g.add_conditional_edges("slots", _then("liaison"), ["liaison", END])
    g.add_conditional_edges("liaison", _then("check"), ["check", END])
    g.add_conditional_edges("check", lambda s: "approval"
                            if s.get("status") == "awaiting_approval" else END, ["approval", END])
    g.add_conditional_edges("approval", _after_approval, ["send", "check", END])
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer, store=store)
