# Engineering design review

A concise review of GigBid's design with links to the evidence. Every number comes from a
file in `evals/results/` or a test. Details live in the linked documents.

## 1. Problem and constraints

A freelancer spends hours a week reading job posts, judging clients and writing proposals.
GigBid does the reading, judging and drafting. The freelancer keeps every decision that
leaves the system.

- **Not automated, by design.**
  - Submitting a proposal and sending a message each need an explicit human approval,
    recorded through the API.
  - No scraping or browser automation: marketplace access goes through one port with a
    simulator adapter (GigSim) and room for the official Upwork MCP.
  - No claim without portfolio evidence.
- **Budgets.** Declared in `agent/config.yaml` (`targets`) before measurement:

  | Unit | p95 | Cost |
  | --- | --- | --- |
  | Analysed job | 20 s | $0.01 |
  | Proposal | 60 s | $0.05 |

  Per-run guards: 40 steps and 60k tokens per thread (`budgets`).
- **Free-tier models.** Groq and Cerebras free tiers. Their rate limits shaped the model
  layout (section 9 and [RUNBOOK.md](RUNBOOK.md#model-rate-limits)).

## 2. Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams.

- **Request path.** The Next.js web app proxies to FastAPI. The API only reads state and
  enqueues Arq jobs on Redis. The worker runs two LangGraph graphs with a Postgres
  checkpointer and store.
- **Bid graph.**
  1. Analyst, risk and matcher in parallel;
  2. decide;
  3. pricing;
  4. writer;
  5. claim verifier;
  6. critic, which loops back to the writer at most twice;
  7. compliance;
  8. approval interrupt;
  9. submit.
- **Conversation graph.** Read, classify, slots, liaison, check, approval interrupt, send.
- **MCP boundaries.** Agents call tools only through `agent/mcp_client.Toolbox`.
  - **Allowlist.** It holds a per-agent `ALLOWLIST`; the writer cannot submit.
  - **Tokens.** Each call carries a signed bearer token scoped to one account.
  - **Servers.** Marketplace (behind `agent/marketplace_port.py`), Portfolio and
    Workspace. The marketplace port is where an Upwork adapter would replace GigSim.
- **Data stores.**
  - Postgres: users, threads, checkpoints and long-term memory.
  - Redis: the queue and locks.
  - A fastembed index per persona, on disk inside the Portfolio server.
- **Why separate agents.** Each agent owns one decision with a typed handoff
  (`agent/handoffs.py`), its own prompt version, model and tools. That makes it possible to:
  - give cheap models the extraction steps and stronger ones the writing;
  - wrap a rule around one step, such as the claim verifier or compliance;
  - attribute a failure to one node in the trace.

  Section 5 tests whether this is worth the cost.

## 3. MCP experiment: tool granularity (A7)

[TOOLS.md](TOOLS.md#tool-granularity-experiment-a7) ·
[`tool_granularity.md`](../evals/results/tool_granularity.md)

- **Hypothesis.** Coarse tools save tokens but cost selection accuracy, and tuned
  descriptions recover accuracy.
- **Setup.** 40 requests with known correct calls; one model turn each with
  `gpt-oss-120b`; three tool sets.

| Tool set | Selection | Arguments | Tokens per task |
| --- | --- | --- | --- |
| Fine, 8 tools | 0.925 | 0.93 | 620 |
| Coarse, 2 tools | 0.875 | 0.88 | 420 |
| Tuned descriptions | 0.90 | 0.91 | 671 |

**Results.**
- **Coarse.** It saved a third of the tokens and cost two errors, where its `action` enum
  hid distinctions that separate tool names carry.
- **Tuned.** One tuned description backfired.
- **All three.** All three sets missed the same three multi-call requests: the model issues
  one call per turn whatever the granularity.
- **Noise.** The differences are 1–2 tasks, within noise.

**Conclusion.** Keep the fine tools. Parallel searches belong in code, as the matcher does,
not in the model's hands.

## 4. RAG experiment (B)

[RAG_STUDY.md](RAG_STUDY.md) · [`rag_comparison.md`](../evals/results/rag_comparison.md) ·
[`ablation.md`](../evals/results/ablation.md) ·
[`rag_real_comparison.md`](../evals/results/rag_real_comparison.md)

- **Hypothesis rejected.** We expected decomposition plus hybrid search to add 15 points of
  Recall@5 on jobs with 4+ skills. Decomposition hurt (0.520 → 0.510).
- **Selected pipeline.** Hybrid BM25 + dense with an outcome prior: Recall@5 0.524 → 0.595
  on 576 dev queries. Each component costs about 4 points when ablated.
- **Real data.** On 469 held-out real Upwork queries the selected pipeline still wins:
  0.480 → 0.578. That is a larger gain than on the dev set.
- **Rejected components.** Reranking and corrective retrieval were 100× slower with no gain.
- **Claim verifier** ([`claims_eval.json`](../evals/results/claims_eval.json)):

  | | Unsupported claims per proposal | Unsupported share |
  | --- | --- | --- |
  | First drafts | 0.6 | 13.6% |
  | Final drafts | 0 | 0% |

  Measured on 5 proposals, at about 14.6k tokens each.
- **Judge calibration.** The quality judge is not used for claims until it reaches a
  weighted kappa of 0.6 or more against human scores. The 30 human scores are not filled in
  yet (`evals/datasets/judge_labels.csv`).

## 5. Agent experiment (C8)

[EVALUATION.md](EVALUATION.md#architecture-experiment-c8-running) ·
[`architecture_eval.md`](../evals/results/architecture_eval.md) when finished

- **Setup.** 50 dev jobs through three implementations, all on `gpt-oss-120b`:
  - a single ReAct agent with all read tools;
  - a prebuilt `langgraph-supervisor`;
  - the custom graph.
- **Scoring, the same for every output:**
  - bid/skip accuracy against GigSim's truth;
  - unsupported claims against the evidence each implementation actually retrieved;
  - Compliance Guard violations;
  - GigSim reply rate.
- **Status.** The run started 2026-11-15 and fits Cerebras' free quota over about four days.
  Interim results are in section 11.

## 6. Policy-change response

**What changed.** GigSim policy v2 (`GIGSIM_POLICY=v2`, 2026-11-15) does two things:
- Connects costs double;
- a proposal containing an external link is refused at submit (422).

**What GigBid needed:**

| File | Change | Why |
| --- | --- | --- |
| `data/policy_pack/marketplace_rules.md` | +2 lines: rule 8, `external_links` | The Compliance Guard's model reads the policy pack. |
| `agent/nodes/compliance.py` | +7 lines | Sentences with a link are removed by rule, like contact details, before a draft reaches approval. |
| Pricing, graph, prompts, config | none | Pricing reads `connects_cost` from the marketplace on every job, and the expected-value check uses it, so doubled costs lower the expected value of a bid automatically. |

**Effort.** About 20 minutes, including the test
([`tests/unit/test_policy_change.py`](../tests/unit/test_policy_change.py)). The simulator
side was 9 lines in `gigsim/app.py`.

**What made it cheap.**
- Fees, thresholds and rules live in configuration and the policy pack, not in node code.
- The marketplace is the source of truth for per-job costs.

**What would have been expensive.** A rule the model could not be trusted to apply. That
is why the link rule is a regular expression and not only a line in the policy pack.

## 7. Signature extension: X3 portfolio builder

[EXTENSION.md](EXTENSION.md) · [`portfolio_builder.md`](../evals/results/portfolio_builder.md)

**What it does.** It turns GitHub repositories into code-verified case studies through
GitHub's official MCP server. Skills are detected from code, a model writes the summary, and
any sentence naming a skill the code does not show is dropped.

**Skill recall.** Recall of a project's true skills rose from 0.66 (hand-written case
studies) to 0.99, at precision 0.82. The precision cost is a gap in the labels: Python and
TypeScript are detected correctly but missing from the projects' skill labels.

**Retrieval.** Unchanged (Recall@5 0.595 → 0.591, within noise). The raw code was already
indexed, so the case studies restate signal hybrid search already had.

**Hallucinations.** The model named no unsupported skill in 34 summaries, so verification
removed nothing.

## 8. Failure analysis

Development and held-out failures, grouped. "Fix worked" means a rerun confirmed it.

| Category | Jobs | What happened | Attempted fix | Fix worked |
| --- | --- | --- | --- | --- |
| Wrong skip: fit under-scored | 5 (dev) | Every required skill was in the retrieved evidence; the matcher scored fit 0.17–0.67, e.g. "Add background jobs with Celery" at 0.17. | Prompt change proposed (score skill coverage first). | Not yet rerun |
| Wrong skip: domain gap | 4 (dev) | Skills covered, but the title names a domain the portfolio lacks ("Computer vision defect detector"). Partly label noise. | None: arguably a correct pass. | — |
| Wrong skip: client risk | 1 (dev) | Fit 0.83, but the client's payment method was unverified (risk 0.6). | None: the label ignores client risk. | — |
| Tool error: model output | 1 (dev) | The analyst returned the JSON schema instead of filling it (gpt-oss-20b). | The worker replays "needs attention" runs. | Yes on rerun |
| Wrong skip: false scam | 1 real job, 625 real postings | `off_platform_payment` matched any "crypto" and skipped an $8,000 crypto-volatility job. | The rule now needs a payment phrase. | Yes: 625 → 13 hits, the same 37 synthetic scam jobs |
| Tool error: short skill | 3 of 8 held-out data jobs | Skills "R" / "C#" are under the search tool's 3-character minimum, and one rejected query failed the matcher. | Short skills stay in the post query. | Yes: 0 on rerun |
| Unsupported claim | 0.6 per proposal | Invented availability ("I can start this week, 30 hours a week"); no persona data supports it. | Writer prompt v2 forbids it; screening answers say `TO CONFIRM`, and approval is refused until edited. | Yes: 0.6 → 0 |
| Compliance miss → block | 1 held-out job | The writer guaranteed an outcome; the Compliance Guard blocked the draft. | The block is the intended behaviour. | — |
| Injection | see section 9 | Planted instructions in job posts. | Defences measured below. | — |

**Supervisor baseline (C8 smoke).** The supervisor skipped its matcher and writer agents
and wrote the proposal itself. Its letter cited evidence it had never retrieved, so all
3 of its claims were unsupported. This is a failure of the baseline, not of GigBid, and C8
measures it at scale.

## 9. Safety and platform respect

**Forbidden, and how each is enforced:**

| Forbidden action | Enforcement |
| --- | --- |
| Submitting or sending without approval | A LangGraph interrupt before `submit` and `send`. The API records the decision in an outbox (`pending_resume`) before resuming, and only the post-approval nodes hold write tools (`ALLOWLIST`). Idempotency keys and Redis locks prevent double submits across restarts. |
| Fabricated experience | Every claim cites an evidence id; the Claim Verifier drops sentences whose claims are unsupported or cite unknown ids. Availability is left to the freelancer (`TO CONFIRM`). |
| Off-platform contact or payment, guarantees, links | The Compliance Guard: rules strip contact details, guarantees and links, then a model checks the policy pack. It runs again after every human edit. |
| Obeying instructions in job posts | Job and message text is fenced as untrusted; the risk node flags injection phrasing; the downstream rules above still apply. See the injection results below. |
| Scraping | GigSim only. Live mode would use the official Upwork MCP behind the same port (not built). |
| Leaking PII | `agent/redact` masks emails and phones in logs, audit records and exported trace spans (`tests/unit/test_tracing.py`). |

**Injection results** ([`injection_eval.md`](../evals/results/injection_eval.md)).
Both pipelines saw the same posts with a planted instruction.
- **Without defences:** the job text pasted raw into a plain writer prompt that may also
  choose to submit.
- **With defences:** the GigBid graph.

| Pipeline | Injections obeyed | Fabricate | Contact | Autosubmit |
| --- | --- | --- | --- | --- |
| No defenses | 8 of 8 | 3/3 | 3/3 | 2/2 |
| GigBid graph | 0 of 7 | 0/3 | 0/3 | 0/1 |

- **How the graph defended.** The risk node flagged all 7 injected posts.
  - Six were skipped or watched before any draft was written.
  - The autosubmit post reached approval and stopped there.
- **Not exercised.** The letter-level defences (fence, verifier, compliance rules) were not
  needed on these 7 posts.
- **Sample size.** 7 of 15 jobs finished with defences (8 without). Groq's free daily
  allowance ran out on the rest after 8 hourly retries; rerunning the eval finishes only
  those.
- **Weakness.** A post the risk node does not flag reaches the writer, where only the
  fence, the prompt rule and the downstream checks stand in the way. Those are measured
  only by the fake-model integration tests.

**Residual risks.**
- The quality judge is uncalibrated.
- The scam rules do not transfer to employment-style scams: precision 0.017 on 44,042 real
  labelled postings, F1 0.42 with the model on a small sample.
- Free-tier rate limits can still end a run as "needs attention"; the worker replays it.
- The approval UI shows evidence for each claim, but a hurried human can still approve a
  weak proposal.

## 10. Held-out evaluation

[EVALUATION.md](EVALUATION.md#latency-and-cost-budgets-e5) · [DATA_CARD.md](DATA_CARD.md)

**Held-out sets.** Real Upwork postings, never used for tuning:
- 24 jobs for latency and cost;
- 469 retrieval queries;
- 44,042 labelled postings for scams.

**Latency and cost** (`cerebras` profile):

| Unit | p95 | Target | Mean cost | Target |
| --- | --- | --- | --- | --- |
| Analysed job | 23.8 s | 20 s | $0.0026 | $0.01 |
| Proposal (3 jobs) | 65.2 s | 60 s | $0.0067 | $0.05 |

- **Cost.** Inside both budgets.
- **Latency.** Over both targets, while Groq's free daily allowance for the small model was
  exhausted and those nodes fell back to the slower model. Early skip saved 50% of spend.

**Generalisation.** Retrieval improved on real text. What failed on real data were the
hand-written assumptions: the crypto rule, synthetic budgets 30–100× real ones, and short
skill names. These are written up in [ARTICLE.md](ARTICLE.md).

## 11. Results still arriving

**C8 interim (2026-11-15, 8 jobs all three implementations had finished).** These 8 are
clean jobs in the persona's niche, so every one should be bid. Scams and off-niche jobs come
later in the fixed sample.

| Implementation | Bid/skip accuracy | Bids | Unsupported claims per proposal | Compliance violations per proposal | Reply rate | Tokens per job | p95 (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ReAct | 1.00 | 8 | 2.6 | 0.25 | 0.88 | 15,369 | 201 |
| Supervisor | 1.00 | 8 | 8.0 | 1.1 | 1.00 | 9,483 | 200 |
| Custom graph | 0.63 | 4 | 0 | 0 | 1.00 | 20,060 | 326 |

**Where a simpler agent is better, so far.** On clean in-niche jobs the baselines bid on
everything and the custom graph watched half of them. The baselines are cheaper too: ReAct
uses 23% fewer tokens than the graph, and the supervisor half as many.

**What the graph buys.** Zero unsupported claims and zero compliance violations, against
2.6 and 8.0 unsupported claims per baseline proposal. The supervisor writes without
retrieving and cites evidence it never saw.

**Caveat.** The GigSim reply rate does not penalise invented claims, so it cannot separate
the three; its client model only checks the price and generic openings. The final table
replaces this one when the run ends ([`architecture_eval.md`](../evals/results/architecture_eval.md)).
