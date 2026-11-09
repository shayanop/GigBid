# Retrieval study (B5, B6)

All numbers come from the 576-query dev set (`evals/datasets/dev_retrieval.jsonl`, see
[DATA_CARD.md](DATA_CARD.md)) on CPU with `BAAI/bge-small-en-v1.5`. Raw results are in
`evals/results/`. Every variant is a set of switches on one shared index (`rag/pipeline.py`),
so differences come from the components, not from re-chunking.

## Hypothesis

Requirement decomposition plus hybrid (dense + BM25) search would raise Recall@5 by 15
points over V0 for jobs with four or more required skills.

**Result: rejected.** Decomposition made 4+-skill recall slightly worse (0.520 → 0.510).
Hybrid alone added 2.7 points. Neither came close to 15.

## Variants ([rag_comparison.md](../evals/results/rag_comparison.md))

| Variant | Components | Recall@5 | MRR | nDCG@10 | Recall@5, 4+ skills | p95 latency (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| V0 | dense only | 0.524 | 0.687 | 0.591 | 0.520 | 41 |
| V1 | decompose | 0.520 | 0.614 | 0.566 | 0.510 | 203 |
| V2 | hybrid | 0.550 | 0.667 | 0.594 | 0.546 | 70 |
| V3 | rerank | 0.526 | 0.652 | 0.564 | 0.511 | 6,655 |
| V4 | outcome | 0.556 | 0.702 | 0.607 | 0.557 | 39 |
| V8 | corrective | 0.526 | 0.652 | 0.563 | 0.511 | 7,811 |
| **Selected** | hybrid, outcome | **0.595** | **0.717** | **0.629** | **0.601** | 54 |

## Ablation ([ablation.md](../evals/results/ablation.md))

| Pipeline | Recall@5 | nDCG@10 | Recall@5 lost |
| --- | --- | --- | --- |
| Selected (hybrid + outcome) | 0.595 | 0.629 | — |
| without hybrid | 0.556 | 0.607 | −0.039 |
| without outcome | 0.550 | 0.594 | −0.045 |

The two gains roughly add up (+0.026 and +0.032 alone, +0.071 together), so the
components help on different queries. BM25 catches exact skill names that the small
embedding model blurs. The outcome prior moves projects behind won proposals up among
near-ties.

## Segments (Recall@5 / nDCG@10, V0 → selected)

| Segment | n | V0 | Selected |
| --- | --- | --- | --- |
| fr_ml | 189 | 0.497 / 0.580 | 0.575 / 0.623 |
| fr_fs | 190 | 0.510 / 0.588 | 0.581 / 0.596 |
| fr_da | 197 | 0.564 / 0.606 | 0.629 / 0.667 |
| 4+ skills | 370 | 0.520 / 0.582 | 0.601 / 0.627 |
| under 4 skills | 206 | 0.532 / 0.609 | 0.585 / 0.633 |

The gain is largest on the jobs the hypothesis was about: +8.1 points on 4+-skill jobs
versus +5.3 on the rest. For fr_fs, nDCG barely moves, because hybrid search helps recall
but reorders the top results less well than dense search does.

## Negative results

- **Decomposition (V1).** Each sub-query hits projects that match a single skill. RRF
  then promotes projects that match one requirement strongly over projects that match
  several weakly, which is the opposite of what a multi-skill job needs. MRR drops from
  0.687 to 0.614.
- **Cross-encoder rerank (V3) and corrective retrieval (V8).** `ms-marco-MiniLM` is
  trained on web question answering, not skill matching. Case studies name only about 60%
  of a project's skills and imply the rest, so the reranker scores those passages low.
  Corrective retrieval reuses the same grader, so it inherits the same error, and with
  threshold 0 it rarely triggers a re-search. Both are also two orders of magnitude
  slower. The eval asks for k=100, so these latencies overstate the deployed case (the matcher asks for k=4 per requirement),
  but they would still be well over V0.

## Deployment choice

`rag.variant: selected` with `components: {hybrid: true, outcome: true}` in
`agent/config.yaml`. It is the best variant on all three quality metrics, and p95
latency rises only from 41 to 54 ms with no extra model download. Rerank and corrective
stay available as presets but are not deployed.

## Caveats

- Lexical methods are flattered by the generator's template text (see DATA_CARD).
- The outcome prior is flattered too. The generator makes proposal outcomes depend on
  how well the cited project matched, so "won" is a cleaner relevance signal here than it
  would be on a real marketplace, where price, timing and the opening line all matter.
  This is also why better retrieval need not mean more replies: GigSim clients penalise
  generic openings regardless of the evidence cited. Reply rate per variant has not been
  measured yet.

## Claim verification and judge (B3, B4)

These need model calls and are run separately:

- `uv run python -m evals.runners.claims_eval --jobs 5` counts unsupported claims per
  proposal before and after the verifier → `evals/results/claims_eval.json`. The first
  attempt hit Groq's free-tier daily token cap (200k per model). Each proposal costs
  about 25k tokens, so keep the sample small and quote its size.
- Judge calibration: fill `human_score` (1–5) for the 30 rows in
  `evals/datasets/judge_labels.csv`, then run
  `uv run python -m evals.runners.judge_calibration score`. This reports
  quadratic-weighted Cohen's kappa → `evals/results/judge_calibration.json`. The judge is
  only used for quality claims once kappa ≥ 0.6.
