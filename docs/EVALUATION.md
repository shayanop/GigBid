# Evaluation: decisions, architecture and budgets (E2, C8, E5)

Retrieval and claim results are in [RAG_STUDY.md](RAG_STUDY.md), tool granularity (A7) in
[TOOLS.md](TOOLS.md#tool-granularity-experiment-a7) and the real datasets in
[DATA_CARD.md](DATA_CARD.md). Every number below comes from a file in `evals/results/`.

## Decisions (E2)

[`evals/runners/decision_eval.py`](../evals/runners/decision_eval.py) runs the bid graph with
real models up to the writer on 60 development jobs: 20 per persona, made of 12 clean jobs
in the persona's niche, 4 scams in it and 4 clean jobs from other niches, fixed by seed 7.

Labels come from GigSim's hidden truth, not from the agent. A job is a bid when it is in the
persona's niche, is not a scam and is not a repost. "Watch" counts as not bidding.

Run on 2026-11-15, `GIGBID_PROFILE=cerebras`
([`decision_eval.md`](../evals/results/decision_eval.md)):

| Jobs | Bid F1 | Bid precision | Bid recall | Scam precision | Scam recall | Price in fair band | Tokens per job | p95 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 60 | 0.82 | 1.00 | 0.69 | 0.92 | 1.00 | 0.76 | 5,845 | 25.7 |

| Label | Agent bid | Agent watch | Agent skip | Error |
| --- | --- | --- | --- | --- |
| bid (36) | 25 | 6 | 4 | 1 |
| skip (24) | 0 | 0 | 24 | 0 |

- **Skip jobs.** The agent never bid on a job it should skip, and it caught all 12 scams.
- **False scam flag.** The one false flag (scam precision 0.92) is a real client with an
  unverified payment method. The risk rule treats that as a skip.
- **Prices.** 76% of the prices fell inside GigSim's fair band.

### Failure analysis: the 11 missed bids

| Group | Jobs | What happened |
| --- | --- | --- |
| Fit under-scored, domain gap | 4 | Every required skill was in the retrieved evidence, but the title names a domain the portfolio never shows: "Computer vision defect detector" (2), "React Native booking app", "Recommendation model for e-commerce store". The fit was 0.40–0.67. The label rule checks skills only, so these are partly label noise. A freelancer could reasonably pass. |
| Fit under-scored, no gap | 5 | Evidence covered every skill and the work itself: "Add background jobs with Celery" scored 0.17 for a portfolio full of Celery work. The others are "Fix performance issues in React app", "Build admin panel with Postgres backend", "LangGraph agent for invoice processing" and a second Celery job. The matcher is conservative. |
| Risk rule | 1 | job_00111: fit 0.83, but the client's payment method is unverified (risk 0.6 > 0.4). The label ignores client risk; the agent's skip is defensible. |
| Model output | 1 | job_00285: the analyst returned the JSON schema instead of filling it. That is a gpt-oss-20b failure seen before in compliance. The run needs attention, and a rerun usually passes. |

**How the evidence was checked.** For each under-scored job I re-ran the matcher's exact
retrieval (the post plus each skill, k = 4, top 20) without the model. Each skill name was
then looked up in the evidence text, and all nine jobs had every skill present. So the
misses come from the matcher's judgement, not from retrieval.

**Fix not yet tried.** Lowering `decision.bid_min_fit` from 0.70 to 0.60 would turn 3 of
the 6 watches into bids, one of them a domain-gap job (the recommendation model, 0.67). Telling the matcher
prompt to score skill coverage first and treat the title's domain as secondary is the
targeted fix. It needs a rerun of this eval to confirm.

## Latency and cost budgets (E5)

The targets were declared in `agent/config.yaml` (`targets`) before any measurement:

| Unit | p95 target | Cost target |
| --- | --- | --- |
| Analysed job | 20 s | $0.01 |
| Proposal | 60 s | $0.05 |

[`evals/runners/budget_eval.py`](../evals/runners/budget_eval.py) measures them on held-out
jobs: 24 real Upwork postings (8 per persona's category, seed 11) served by GigSim's real
mode. No prompt, threshold or retriever choice was tuned on these jobs. The graph runs as
deployed (`cerebras` profile) up to approval.

Each call is priced from the model that actually answered, at list prices (`prices` in
the config, read 2026-11-15): Groq gpt-oss-20b $0.075 in / $0.30 out per 1M tokens, Groq
gpt-oss-120b $0.15 / $0.60, Cerebras gpt-oss-120b $0.35 / $0.75. The free tiers cost
nothing; these figures are what the same traffic would cost on paid plans.

Run on 2026-11-15 ([`budget_eval.md`](../evals/results/budget_eval.md)):

| Unit | Jobs | p50 (s) | p95 (s) | Target p95 (s) | Mean cost (USD) | Target (USD) |
| --- | --- | --- | --- | --- | --- | --- |
| Analysed job | 24 | 15.1 | 23.8 | 20 | 0.0026 | 0.01 |
| Drafted proposal | 3 | 40.1 | 65.2 | 60 | 0.0067 | 0.05 |

- **Cost.** Cost is well inside both budgets: a quarter of the analysis budget and an
  eighth of the proposal budget.
- **Latency, analysed job.** The p95 misses its target by 19% (23.8 s against 20 s).
- **Latency, proposal.** The p95 misses by 9% (65.2 s against 60 s), but on only 3
  proposals, so the proposal figure is not reliable.
- **Why latency was high.** Groq's free daily allowance for gpt-oss-20b had run out on
  earlier runs that day. Only 2 of 24 jobs got an answer from it, so the small nodes
  (analyst, risk, pricing, compliance) fell back to gpt-oss-120b. That made them slower and
  roughly twice as expensive. The miss reflects the free tier, not the design; a paid
  Groq tier would remove it. Rerun on a fresh day before quoting the latency.
- **Two held-out failures.** The first run failed on 3 of 8 data-analysis jobs. Real
  Upwork skill names include "R", "C" and "C#", shorter than the 3-character minimum of
  `search_evidence`, and one rejected query failed the whole matcher. The matcher now
  leaves such skills to the post query (`agent/nodes/matcher.py`); the rerun had none of
  these errors. Its one failure was the Compliance Guard blocking a draft for a guarantee.
- **Mostly skips.** 20 of the 24 real jobs ended as skip or watch. The run does not record
  why. Given that 35% of real clients are unverified and 48% have no spend (DATA_CARD.md),
  the client-risk rule is the likely cause, but this is unconfirmed.

### Optimization: early skip

Watch and skip jobs stop at the decision, so they never pay for pricing, writer, verifier,
critic and compliance. On this run the 24 jobs cost $0.076. Had all 24 been drafted, they
would have cost $0.151 (each stopped job given the measured average cost of the drafting
half), so the early stop saved 50% of the spend.

A second optimization is spreading nodes across rate-limit buckets (`cerebras` profile,
[RUNBOOK.md](RUNBOOK.md#model-rate-limits)). Before it, the claims eval failed on rate limits
after 4 proposals; afterwards it measured 5 of 5 (RAG_STUDY.md).

## Architecture experiment (C8): running

[`evals/runners/architecture_eval.py`](../evals/runners/architecture_eval.py) runs the same 50
development jobs through three implementations:
- a single ReAct agent with every read-only tool;
- a prebuilt `langgraph-supervisor` with researcher, matcher and writer agents;
- the custom graph.

All three use gpt-oss-120b on Cerebras (profile `c8`, no fallback to another host), so only
the architecture differs. Every output is scored the same way:
- bid/skip accuracy against GigSim's truth;
- unsupported claims, from the verifier run on the final letter against the evidence that
  implementation actually retrieved;
- violations found by the Compliance Guard;
- reply rate from each implementation's own GigSim copy.

**How the run fits the free quota.** It needs roughly 4M tokens against Cerebras' free
quota of 1M tokens a day and 150 requests an hour. Calls are paced at 2.4 a minute, and
each job goes through all three implementations before the next, so partial results stay
comparable. Finished rows are kept in `evals/results/architecture_rows.jsonl`. When the
quota runs out the run waits an hour and resumes; it started on 2026-11-15 and should
finish in about four days.

Started with:

```bash
uv run python -m evals.runners.architecture_eval --jobs 50 --fresh --wait
```

If the machine restarts, rerun it without `--fresh` (finished rows are skipped). Only do that when no run is going: two runs at once share the quota and write duplicate rows.

What the smoke tests showed:
- **Supervisor.** It ignored its own plan on the first job: after the researcher it wrote
  the proposal itself, skipping the matcher and writer. So its letter cited evidence it had
  never retrieved, and all 3 of its claims were unsupported.
- **Supervisor output.** `langgraph-supervisor` returned no structured answer despite
  `response_format`. The runner adds the same final extraction call that
  `create_react_agent` makes, and counts its tokens.
- **Earlier model choice.** The run first used gpt-oss-20b on NIM and Groq. NIM took
  70–106 s per call on 2026-11-15, and one 8k-a-minute Groq bucket could not hold a
  proposal.
