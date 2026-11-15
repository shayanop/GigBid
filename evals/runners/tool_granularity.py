"""Tool granularity experiment (A7, research question A): does the shape of the tool set
change what the agent calls? 40 requests with known correct calls
(evals/datasets/tool_tasks.jsonl) go to one model with three tool sets:

- fine: the eight read-only MCP tools as the servers define them today;
- coarse: two tools, marketplace(action, ...) and portfolio(action, ...);
- tuned: the fine tools with descriptions that say when to use each and with what.

Each request gets one model turn and the tool calls it makes are scored, without running
them. A request whose second call needs the first one's result (a client id from a job)
expects only the first. Selection is right when the multiset of tools called equals the
expected one; an argument is right when ids match exactly and free-text arguments contain
the expected keywords.

Run: uv run python -m evals.runners.tool_granularity [--model cerebras:gpt-oss-120b]
"""

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime

from agent.config import _build, load_config
from evals.runners.rag_eval import RESULTS, ROOT
from mcp_servers.marketplace import server as marketplace
from mcp_servers.portfolio import server as portfolio

TASKS = ROOT / "evals" / "datasets" / "tool_tasks.jsonl"
READ = ["search_jobs", "get_job", "get_client_history", "get_connects_balance",
        "list_messages", "search_evidence", "get_case_study", "list_skills"]
SYSTEM = ("You are a freelancer's assistant with marketplace and portfolio tools. Make the "
          "tool calls needed to start on the request now, calling independent tools together. "
          "If a call needs a value you do not have yet, such as a client id, make only the "
          "call that gets it.")

TUNED = {
    "search_jobs": "Find open jobs to bid on by keywords or skills. Only for discovering new "
                   "jobs: to read a job whose id you know, use get_job.",
    "get_job": "Read one job by its id (job_00012): title, full description, budget, "
               "timeline, skills, screening questions and the client_id of whoever posted it.",
    "get_client_history": "Read a client's record by client id (cl_0042): payment "
                          "verification, total spend, hire rate, rating and reviews. To judge "
                          "the client of a job, call get_job first to get its client_id.",
    "get_connects_balance": "How many Connects the freelancer has left to bid with.",
    "list_messages": "The freelancer's conversations with clients, including new replies to "
                     "proposals.",
    "search_evidence": "Search the freelancer's portfolio for proof of one requirement, e.g. "
                       "'Stripe payments'. Call once per requirement; put the skill or task in "
                       "requirement. Results carry ids to cite in proposals.",
    "get_case_study": "Read one case study in full by its project id (fr_ml-p09).",
    "list_skills": "Every skill named in the portfolio, with how many documents mention it.",
}

COARSE = [
    {"type": "function", "function": {
        "name": "marketplace",
        "description": "Read from the freelance marketplace. action: search_jobs (find open "
                       "jobs by query and skills), get_job (one job by job_id), get_client "
                       "(a client's history by client_id), connects (Connects balance), "
                       "messages (client conversations).",
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string", "enum": ["search_jobs", "get_job", "get_client",
                                                  "connects", "messages"]},
            "job_id": {"type": "string"}, "client_id": {"type": "string"},
            "query": {"type": "string"}, "skills": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {
        "name": "portfolio",
        "description": "Read the freelancer's portfolio. action: search (evidence for one "
                       "requirement in query), case_study (one case study by case_id), skills "
                       "(every skill the portfolio names).",
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string", "enum": ["search", "case_study", "skills"]},
            "query": {"type": "string"}, "case_id": {"type": "string"}}}}},
]
TO_COARSE = {"get_job": ("marketplace", "get_job"),
             "get_client_history": ("marketplace", "get_client"),
             "get_connects_balance": ("marketplace", "connects"),
             "list_messages": ("marketplace", "messages"),
             "search_jobs": ("marketplace", "search_jobs"),
             "search_evidence": ("portfolio", "search"),
             "get_case_study": ("portfolio", "case_study"),
             "list_skills": ("portfolio", "skills")}


async def tool_sets() -> dict[str, list[dict]]:
    specs = {t.name: t for s in (marketplace.mcp, portfolio.mcp) for t in await s.list_tools()}

    def fn(name: str, description: str) -> dict:
        return {"type": "function", "function": {"name": name, "description": description,
                                                 "parameters": specs[name].input_schema}}
    return {"fine": [fn(n, specs[n].description) for n in READ],
            "coarse": COARSE,
            "tuned": [fn(n, TUNED[n]) for n in READ]}


def key(call: dict, coarse: bool) -> tuple:
    return (call["name"], call["args"].get("action")) if coarse else (call["name"], None)


def expected_key(call: dict, coarse: bool) -> tuple:
    return TO_COARSE[call["tool"]] if coarse else (call["tool"], None)


def args_ok(expected: dict, got: dict) -> bool:
    text = json.dumps(got).lower()
    return all(all(k in text for k in v) if name == "keywords" else got.get(name) == v
               for name, v in expected.items())


def score(task: dict, calls: list[dict], coarse: bool) -> dict:
    want = [expected_key(c, coarse) for c in task["calls"]]
    got = [key(c, coarse) for c in calls]
    remaining, right = list(calls), 0
    for exp in task["calls"]:  # pair each expected call with an unused call to the same tool
        match = next((c for c in remaining if key(c, coarse) == expected_key(exp, coarse)
                      and args_ok(exp["args"], c["args"])), None)
        if match:
            remaining.remove(match)
            right += 1
    return {"selection_ok": Counter(want) == Counter(got), "args_right": right,
            "args_expected": len(task["calls"])}


async def run(model_spec: str) -> dict:
    load_config()  # loads .env
    tasks = [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines()]
    sets, base = await tool_sets(), _build(model_spec, None, "judge")
    out = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "model": model_spec, "tasks": len(tasks), "sets": {}}
    for name, tools in sets.items():
        llm, rows = base.bind_tools(tools), []
        for task in tasks:
            try:
                msg = await llm.ainvoke([{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": task["request"]}])
                calls = [{"name": c["name"], "args": c["args"]} for c in msg.tool_calls]
                tokens = (msg.usage_metadata or {}).get("total_tokens", 0)
                error = None
            except Exception as e:  # noqa: BLE001 - a failed call scores as no calls
                calls, tokens, error = [], 0, f"{type(e).__name__}: {e}"[:200]
            row = {"id": task["id"], "calls": calls, "tokens": tokens, "error": error,
                   **score(task, calls, name == "coarse")}
            print(name, task["id"], "ok" if row["selection_ok"] else "WRONG", calls, flush=True)
            rows.append(row)
        out["sets"][name] = {
            "selection_accuracy": round(statistics.mean(r["selection_ok"] for r in rows), 3),
            "argument_accuracy": round(sum(r["args_right"] for r in rows)
                                       / sum(r["args_expected"] for r in rows), 3),
            "tokens_per_task": round(statistics.mean(r["tokens"] for r in rows)),
            "no_call": sum(not r["calls"] for r in rows),
            "errors": sum(bool(r["error"]) for r in rows), "rows": rows}
    return out


def table(result: dict) -> str:
    lines = [f"Model: {result['model']}, {result['tasks']} tasks.", "",
             ("| Tool set | Tools | Selection accuracy | Argument accuracy | Tokens per task "
             "| No call made | Errors |"), "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, s in result["sets"].items():
        n = 2 if name == "coarse" else len(READ)
        lines.append(f"| {name} | {n} | {s['selection_accuracy']} | {s['argument_accuracy']} "
                     f"| {s['tokens_per_task']} | {s['no_call']} | {s['errors']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="cerebras:gpt-oss-120b")
    args = parser.parse_args()
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    result = asyncio.run(run(args.model), loop_factory=loop)
    (RESULTS / "tool_granularity.json").write_text(json.dumps(result, indent=1),
                                                   encoding="utf-8")
    (RESULTS / "tool_granularity.md").write_text(table(result), encoding="utf-8")
    print(table(result))


if __name__ == "__main__":
    main()
