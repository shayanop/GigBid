"""CI smoke evaluation (E2): 30 development jobs through the decision eval and 3 drafted
proposals through the claims eval, with real models, gated by `eval_gates` in
agent/config.yaml. Exits 1 when a gate fails, so a pull request that lowers bid/skip F1 or
lets unsupported claims through fails CI.

Run: GIGBID_PROFILE=cerebras uv run python -m evals.runners.smoke
"""

import asyncio
import json
import sys
from datetime import UTC, datetime

from agent.config import load_config, profile_name
from evals.runners import claims_eval, decision_eval
from evals.runners.rag_eval import RESULTS


def gate(decision: dict, claims: dict, gates: dict) -> dict[str, dict]:
    after = claims.get("after_verification") or {}
    checks = {
        "bid_f1": (decision["bid_f1"], ">=", gates["min_bid_f1"]),
        "unsupported_per_proposal": (after.get("unsupported_per_proposal"), "<=",
                                     gates["max_unsupported_per_proposal"]),
        "proposals_measured": (claims.get("proposals_measured"), ">=",
                               gates["min_proposals_measured"]),
        "errors": (decision["errors"], "<=", gates["max_errors"]),
    }
    return {name: {"value": v, "rule": f"{op} {limit}",
                   "ok": v is not None and (v >= limit if op == ">=" else v <= limit)}
            for name, (v, op, limit) in checks.items()}


async def run() -> dict:
    load_config()
    decision_eval.ROWS = RESULTS / "smoke_rows.jsonl"  # keep the full eval's rows apart
    decision = await decision_eval.run(10, fresh=True)
    claims = await claims_eval.run(3)
    checks = gate(decision["scores"], claims, load_config()["eval_gates"])
    return {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "profile": profile_name(), "checks": checks, "decision": decision["scores"],
            "claims": {k: v for k, v in claims.items() if k != "per_job"}}


def main() -> None:
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    result = asyncio.run(run(), loop_factory=loop)
    (RESULTS / "smoke.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    for name, c in result["checks"].items():
        print(f"{'PASS' if c['ok'] else 'FAIL'} {name} = {c['value']} (needs {c['rule']})")
    sys.exit(0 if all(c["ok"] for c in result["checks"].values()) else 1)


if __name__ == "__main__":
    main()
