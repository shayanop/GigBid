# Delivery checklist

The spec's project artifacts and requirements, with where each one lives and what is left.
"Owner" marks steps that need your accounts or your judgement.

## Built and measured

| Item | Where |
| --- | --- |
| Multi-agent bid and conversation graphs with approval interrupts | `agent/graphs/`, [ARCHITECTURE.md](ARCHITECTURE.md) |
| MCP servers, allowlists, signed tokens, schema snapshots | `mcp_servers/`, [TOOLS.md](TOOLS.md), `tests/contract/` |
| RAG variants, ablation, real-data check, deployment choice | [RAG_STUDY.md](RAG_STUDY.md) |
| Claim verifier, before and after | [RAG_STUDY.md](RAG_STUDY.md#claim-verification-and-judge-b3-b4) |
| Tool granularity experiment (A7) | [TOOLS.md](TOOLS.md#tool-granularity-experiment-a7) |
| Decision eval (E2) and failure analysis | [EVALUATION.md](EVALUATION.md) |
| Latency and cost budgets on held-out data (E5) | [EVALUATION.md](EVALUATION.md#latency-and-cost-budgets-e5) |
| Prompt-injection success with and without defenses (E4) | `evals/results/injection_eval.md`, [DESIGN_REVIEW.md](DESIGN_REVIEW.md) section 9 |
| Policy-change response | [DESIGN_REVIEW.md](DESIGN_REVIEW.md) section 6, `tests/unit/test_policy_change.py` |
| Signature extension X3 | [EXTENSION.md](EXTENSION.md) |
| Real datasets with attribution and licensing | [DATA_CARD.md](DATA_CARD.md) |
| CI: tests, contracts, Playwright, secrets scan, gated smoke eval | `.github/workflows/ci.yml`, `evals/runners/smoke.py` |
| Tracing code (Phoenix), trace id end to end, PII redaction | `agent/tracing.py`, [RUNBOOK.md](RUNBOOK.md#tracing-phoenix) |
| `docker compose up` stack | `infra/docker-compose.yml` |
| Free public deployment: Hugging Face Docker Space, built and run locally the way the Space runs it | `infra/hf/`, [DEPLOY.md](DEPLOY.md) |
| Paid alternative: Render Blueprint | `render.yaml`, [DEPLOY.md](DEPLOY.md#alternative-render-about-38-a-month) |
| Distributable Portfolio MCP server (Docker) with its own README | [mcp_servers/portfolio/README.md](../mcp_servers/portfolio/README.md) |
| Technical article, 1,454 words | [ARTICLE.md](ARTICLE.md) |
| Engineering design review | [DESIGN_REVIEW.md](DESIGN_REVIEW.md) |
| AI usage disclosure | [AI_USAGE.md](AI_USAGE.md) |

## In progress

- **Architecture experiment (C8).** Running in the background; it stops each day when
  Cerebras' quota runs out and carries on an hour later (about four days in all). When it
  finishes, `evals/results/architecture_eval.md` holds the table for the README and
  [EVALUATION.md](EVALUATION.md). Avoid other Cerebras-heavy runs while it runs.

## Needs you (owner)

1. **Commit and push.** Nothing from the recent sessions is committed.
2. **Deploy the Hugging Face Space (free).** Log in with a write token, run
   `uv run python infra/hf/push.py <user>/gigbid`, then add `GROQ_API_KEY`, `DEMO_EMAIL`
   and `DEMO_PASSWORD` as Space secrets ([DEPLOY.md](DEPLOY.md)).
3. **Judge calibration.** The 30 scores in `evals/datasets/judge_labels.csv` are
   placeholders from the coding assistant (kappa 0.52). Replace each `human_score` with your
   own (1–5), set `rater` to your name, then run:

   ```bash
   uv run python -m evals.runners.judge_calibration score
   ```

4. **Phoenix Cloud and three public traces.** Set the two env vars, run the three bids in
   [DEMO.md](DEMO.md#traces-for-the-readme), share the traces and add the links to the
   README.
5. **Demo video and GIF.** Record them from the shot list in [DEMO.md](DEMO.md).
6. **Two résumé bullets.** Drafts, each reproducible from `evals/results/`:
   - Built a multi-agent freelancer copilot (LangGraph, MCP, FastAPI, Next.js). It drafts
     evidence-cited proposals with human approval, and a claim verifier cut unsupported
     claims from 0.6 to 0 per proposal (`claims_eval.json`). Its bid/skip decisions reach F1
     0.82 at precision 1.00 on 60 jobs (`decision_eval.json`).
   - Chose the retrieval pipeline by ablation: hybrid BM25 + dense with an outcome prior
     raised Recall@5 from 0.524 to 0.595 on 576 dev queries, and from 0.480 to 0.578 on 469
     held-out real Upwork postings (`rag_comparison.md`, `rag_real_comparison.md`).

## Practical failure checks (spec section 13)

| # | Check | Covered by |
| --- | --- | --- |
| 1 | Marketplace MCP down: degraded mode, work queued | `apps/web/tests/e2e/degraded.spec.ts` |
| 2 | Approve, crash before transmission, exactly-once submit | `test_decision_applied_before_a_crash_is_not_applied_twice`, `test_crash_after_submit_retries_without_double_charge`, `test_inbox_to_approval_survives_api_restart_and_submits_once` |
| 3 | Unsupported claim disappears | `test_bid_revises_at_most_twice...` (a claim citing a non-existent evidence id is dropped before the critic) |
| 4 | Trace of a wrong skip, responsible node | [EVALUATION.md](EVALUATION.md) failure analysis (matcher fit, from the decision rows) |
| 5 | Prompt injection: defenses and weaknesses | `evals/runners/injection_eval.py`, [DESIGN_REVIEW.md](DESIGN_REVIEW.md) section 9 |
| 6 | What memory learned; delete it in the UI | `test_memory_shows_what_an_edit_taught_and_forgets_on_request`, Settings page |
| 7 | GigSim to Upwork with the graph unchanged | Partly: the graph only sees `agent/marketplace_port.py`; there is no Upwork adapter to switch to |
| 8 | Human vs judge disagreements | `evals/results/judge_calibration.json`, on placeholder assistant scores until owner step 3 |
| 9 | Where the single agent beats the graph | C8, running |
| 10 | Policy change and its diff | [DESIGN_REVIEW.md](DESIGN_REVIEW.md) section 6 |

## Known gaps

- **Live Upwork mode.** Only the port and its documentation exist; there is no Upwork adapter.
- **Matcher fix untested.** The fix for under-scored fit is proposed in the failure
  analysis but not rerun.
