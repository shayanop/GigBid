"""Runs the starter kit's first end-to-end experiment on GigBid's real bid graph: each sample
job from the kit goes through scout, analyst, risk, matcher, decide, pricing, writer, verifier,
critic and compliance, stopping at approval. The kit's freelancer and portfolio items become a
temporary persona; its jobs and client are added to an in-process GigSim.

A job with `warning_signals` is expected to be skipped; any other job is expected to get a bid.
The signals are only used for that check, never shown to the agents.

Run: uv run python -m evals.runners.kit_sample [path/to/kit/data/sample]
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.config import load_config
from rag import retriever

KIT = Path(__file__).resolve().parents[2] / "gigbid-starter-kit" / "data" / "sample"


def _load(folder: Path, name: str) -> list[dict]:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def write_persona(root: Path, freelancer: dict, items: list[dict]) -> None:
    """One case study per portfolio item; the evidence id becomes the document id."""
    studies = root / freelancer["freelancer_id"] / "case_studies"
    studies.mkdir(parents=True)
    for item in items:
        (studies / f"{item['evidence_id']}.md").write_text(
            f"# {item['title']}\n\n## Approach\n{item['summary']}\n"
            f"Skills: {', '.join(item['skills'])}\n\n## Outcome\n{item['outcome']}\n",
            encoding="utf-8")


def add_to_gigsim(state: dict, freelancer: dict, jobs: list[dict], clients: list[dict]) -> None:
    now = datetime.now(UTC)
    state["freelancers"][freelancer["freelancer_id"]] = {
        "id": freelancer["freelancer_id"], "name": freelancer["display_name"],
        "title": freelancer["headline"], "connects": 120}
    paid = [j["budget"]["max"] for j in jobs if j["budget"]["max"]]
    for c in clients:
        # Not in the kit's data: country, spend, hire rate, age. Spend is estimated as
        # completed projects x the kit's average paid budget; a 0 would read as a brand-new
        # client and make risk flag "no spend history".
        spend = c["completed_projects"] * sum(paid) / max(len(paid), 1)
        state["clients"][c["client_id"]] = {
            "id": c["client_id"], "name": c["client_id"], "country": "unknown",
            "payment_verified": c["payment_verified"], "total_spend": spend, "hire_rate": 0.5,
            "jobs_posted": c["completed_projects"], "rating": c["average_rating"], "reviews": [],
            "member_since": (now - timedelta(days=365)).isoformat(),
            "_prefs": {"dislikes_generic_opening": True, "budget_ceiling_pct": 1.0}}
    for j in jobs:
        state["jobs"][j["job_id"]] = {
            "id": j["job_id"], "title": j["title"],
            "description": f"{j['description']} Expected timeline: {j['duration_days']} days.",
            "skills": j["required_skills"], "budget_type": "fixed",
            "budget_min": j["budget"]["min"], "budget_max": j["budget"]["max"],
            "posted_at": now.isoformat(), "connects_cost": j["connects_cost"],
            "client_id": clients[0]["client_id"],  # the kit's jobs name no client
            "screening_questions": j["screening_questions"],
            "_truth": {"scam": bool(j["warning_signals"]), "injection": False,
                       "duplicate_of": None, "fair_band": None}}


async def run(folder: Path) -> int:
    import gigsim.app
    from agent.graphs import bid_graph

    freelancer = _load(folder, "freelancers.json")[0]
    jobs, clients = _load(folder, "jobs.json"), _load(folder, "client_history.json")
    tmp = Path(tempfile.mkdtemp(prefix="gigbid-kit-"))
    write_persona(tmp / "personas", freelancer, [
        i for i in _load(folder, "portfolio_items.json")
        if i["freelancer_id"] == freelancer["freelancer_id"]])
    retriever.PERSONAS_DIR, retriever.INDEX_DIR = tmp / "personas", tmp / "index"
    retriever.VERIFIED_DIR = tmp / "verified"
    os.environ["MARKETPLACE_LOCAL_USER"] = os.environ["PORTFOLIO_LOCAL_USER"] = \
        freelancer["freelancer_id"]

    create_app = gigsim.app.create_app

    def with_kit(*args, **kwargs):
        app = create_app(*args, **kwargs)
        add_to_gigsim(app.state.data, freelancer, jobs, clients)
        return app
    gigsim.app.create_app = with_kit

    misses = 0
    for job in jobs:
        print(f"\n===== {job['job_id']}: {job['title']}")
        state = await bid_graph._demo(job["job_id"])
        expected = "skip" if job["warning_signals"] else "bid"
        got = state["decision"].action if "decision" in state else state.get("status")
        ok = got == expected
        misses += not ok
        print(f"===== expected {expected}, got {got}: {'OK' if ok else 'MISMATCH'}")
    return misses


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_config()  # loads .env
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else KIT
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(run(folder), loop_factory=loop))


if __name__ == "__main__":
    main()
