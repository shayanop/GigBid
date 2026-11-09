# AI Usage Disclosure

## Tool

Claude Code (Anthropic, Claude Opus models) was used in the Claude desktop app as a coding
assistant throughout the project. The team chose the scope of each phase, the model providers
(Groq, then NVIDIA NIM as an option) and the trade-offs. The team reviewed the changes and made
every commit; the assistant did not commit or push.

## What it helped with

| Area | Files |
| --- | --- |
| Planning from the specification | phase plan, folder layout |
| GigSim stub and synthetic data | `gigsim/`, `data/personas/generate.py`, `evals/datasets/` |
| MCP servers and client | `mcp_servers/*`, `agent/mcp_client.py`, `tests/contract/` |
| Retrieval and evaluation | `rag/`, `evals/runners/*`, `docs/RAG_STUDY.md`, `docs/DATA_CARD.md` |
| Agents and graphs | `agent/nodes/*`, `agent/graphs/*`, `agent/handoffs.py`, `agent/prompts/*`, `agent/memory/*` |
| API, worker and web app | `apps/api/*`, `worker/main.py`, `apps/web/*` |
| Infrastructure and CI | `infra/*`, `.github/workflows/ci.yml`, `Makefile` |
| Documentation | `README.md`, `docs/*`, `CLAUDE.md` |

## Incorrect suggestions that were detected and corrected

1. **Hybrid search that did nothing.** The first hybrid (dense + BM25) retriever fused both
   rankings, then re-sorted the single-query results by cosine score, which threw the BM25
   signal away. V2 scored the same as V0. A unit test with an embedder that deliberately
   misranks documents exposed it, and the scoring path was restructured (`rag/pipeline.py`,
   `_scores`).
2. **Outcome boost of zero.** The outcome prior was scaled by the score spread, which is zero
   when candidate scores tie, so the boost vanished exactly when it should break ties. Fixed
   with a fallback scale (`spread or 1.0`).
3. **Citations sent to clients.** The draft's `[evidence_id]` citations would have gone out in
   the submitted proposal. Caught while reviewing the submit payload. `client_text()` now
   strips them before anything leaves GigBid.
4. **Verifier sentences not matching the draft.** The verifier quotes sentences slightly
   differently from the draft (punctuation, spacing), so exact-match removal left unsupported
   claims in place. Replaced with normalised fuzzy matching (`common.drop_sentences`).
5. **Error handler on parallel nodes.** The assistant relied on LangGraph's node
   `error_handler` for the parallel analysis branches. It does not fire when sibling tasks
   share a superstep, so a failing branch crashed the run. Each branch now contains its own
   timeout and error handling (`_contained`).
6. **Price floor leaked to clients.** An early liaison prompt gave the model the freelancer's
   minimum rate in every reply, and it repeated it to a client. The floor is now passed only
   for negotiation messages.
7. **CI guesses.** A suggested `astral-sh/setup-uv@v10` tag did not exist, and the API module
   built the app at import time, which needed `SESSION_SECRET` in CI. These were fixed by
   pinning an exact action version and exposing only a `create_app()` factory.
8. **Slow model defaults.** NVIDIA NIM's Nemotron Ultra returned the same verifier labels with
   hidden reasoning turned off, about 4.6× faster. With reasoning on, calls timed out and fell
   back. Reasoning is now on only for the writing nodes, and the team chose to keep Groq as the
   default profile.

## Responsibility

All measurements in `evals/results/` come from running the code; none were written by hand.
The judge-calibration labels in `evals/datasets/judge_labels.csv` must come from a human, not
from the assistant.
