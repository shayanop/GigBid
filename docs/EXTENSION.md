# Signature Extension: X3 Portfolio Builder

**What it does.** It turns the freelancer's code repositories into short, code-verified case
studies and adds them to the portfolio index the agents search. A freelancer's case studies
usually name only part of the stack ("moved slow work into a background task queue" instead of
"Celery"). Their code names all of it. The builder makes the code's evidence explicit and
citable without ever claiming a skill the code does not show.

Code: `rag/portfolio_builder.py`. Evaluation: `evals/runners/portfolio_builder_eval.py`.
Results: [portfolio_builder.md](../evals/results/portfolio_builder.md) and `portfolio_builder.json`.

## Design

1. **Read.** It reads repositories through GitHub's official MCP server (`get_file_contents`,
   read-only; see [TOOLS.md](TOOLS.md) for the trust rationale). `--source local` reads the
   same folders from disk for offline runs and tests.
2. **Detect.** It finds skills in the code with deterministic rules: imports (`from celery
   import Celery`), file types (`.tsx`, `Dockerfile`, `.lkml`) and SQL markers (`USE
   WAREHOUSE`, dbt `{{ config(...) }}`). Each detected skill keeps the file and line that shows
   it. No model is involved, so this step cannot hallucinate.
3. **Write.** A model (node `portfolio_builder`, prompt `agent/prompts/portfolio_builder.md`)
   writes a title and a two-to-four-sentence summary from the README, fenced as untrusted, and
   the detected stack.
4. **Verify.** Summary sentences that name a skill the code does not show are dropped, and
   claimed skills are cut down to the detected set. The drops are counted as caught
   hallucinations.
5. **Index.** It writes `data/verified_case_studies/<persona>/<project>.md` (summary plus a
   "Code-verified stack" list with file and line). The index loads these as type
   `verified_case_study` under the same project id when `rag.verified_case_studies` is true.
   The Portfolio MCP server then returns them from `search_evidence`.

## Experiment

**Hypothesis.** Code reveals skills the hand-written case studies leave implicit, so
code-verified case studies raise skill recall per project and, through it, evidence
retrieval.

**Setup.**
- Data: 34 repositories across the three personas (12 `fr_ml`, 13 `fr_fs`, 9 `fr_da`), scored
  against the generator's true project skills (`evals/datasets/persona_truth.json`).
- Source: the repositories read live through GitHub's MCP server from this project's public repository.
- Model: the `open` profile (Groq `gpt-oss-20b`), with one call per repository.
- Retrieval: the deployed hybrid + outcome pipeline on all 576 dev queries, with and without
  the verified case studies in the index.

### Skill evidence per project

| Source | Precision | Recall |
| --- | --- | --- |
| Hand-written case study | 0.961 | 0.658 |
| README | 0.000 | 0.000 |
| Code detector | 0.809 | 0.940 |
| **Case study + code detector** | **0.818** | **0.993** |
| Model summary, before verification | 0.807 | 0.899 |
| Model summary, after verification | 0.807 | 0.899 |

The code recovers 50 of the 51 skills that the case studies only imply. Every one of the
detector's misses is a BI tool (Power BI, Tableau, Excel), which leaves no code behind.

Every precision loss is Python or TypeScript. They are detected correctly from
`.py` and `.tsx` files, but the projects' skill labels do not list them. This is a gap in the
labels, not a false claim: the code really is written in those languages.

### Retrieval (deployed pipeline, 576 queries)

| Index | Recall@5 | MRR | nDCG@10 | Recall@5, jobs with a repo project (n=498) | p95 latency |
| --- | --- | --- | --- | --- | --- |
| Without verified case studies | 0.595 | 0.717 | 0.629 | 0.584 | 26 ms |
| With verified case studies | 0.591 | 0.721 | 0.628 | 0.581 | 25 ms |

### Findings

- **Skill evidence: supported.** Adding code-backed skills lifts recall of a project's real
  skills from 0.66 to 0.99 at a small precision cost, and that cost comes from the labels
  rather than the code.
- **Retrieval: not supported.** Recall@5 moves by −0.004 and MRR by +0.004, both within noise. An earlier build from disk, with different model wording, measured −0.001 and +0.005. The
  raw code files were already indexed under the same project ids, and hybrid search already
  matches import names such as `celery` in them. The new case studies restate that signal in
  prose, so the project ranking does not change. This mirrors the RAG study's warning that
  better evidence need not move the downstream metric.
- **Hallucinations: none caught.** Given the detected stack, the model mentioned no skill
  without code evidence in all 34 summaries, so verification removed nothing. One earlier
  build did drop a sentence, but wrongly: "...with models.sql setting the analytics
  warehouse" was read as claiming the skill SQL. File names are now ignored when matching
  skills, and a unit test covers this case. The
  verification step is still exercised by unit tests (`tests/unit/test_portfolio_builder.py`)
  and guards against drift with other models or noisier READMEs.

**Deployment choice.** Verified case studies are indexed (`rag.verified_case_studies: true`).
They cost nothing in retrieval quality or latency, and they give the writer and the claim
verifier evidence that names each skill in plain words. The writer can cite "Celery: tasks.py"
instead of a bare import line. Whether this lowers unsupported claims per proposal is not
measured yet; the claims eval needs model quota.

## Limitations

- **Hand-written rules.** The detection rules cover the 39 GigSim skills and were written with
  this synthetic code in view, so the detector's recall here is optimistic. Real repositories
  declare dependencies in `requirements.txt`, `pyproject.toml` and `package.json`, which the
  detector does not parse yet.
- **Synthetic repositories.** They are tiny (one to five files) and their READMEs are
  deliberately vague, so the README row is a floor rather than a typical value.
- **GitHub's server.** It occasionally answers a request for an existing file with "Failed to
  get file contents" and no data, or with a protocol-level error. The builder retries both.
  The unit tests use an in-process server that returns the same structured content as the
  real one; `pytest -m live` (needs `GITHUB_TOKEN`) checks the real server.
- **Run-to-run variation.** Model wording changes between builds, so the summary rows vary
  slightly. The detector rows are deterministic.

## Run it

```bash
uv run python -m rag.portfolio_builder fr_ml fr_fs fr_da                  # via GitHub MCP (GITHUB_TOKEN)
uv run python -m rag.portfolio_builder fr_ml fr_fs fr_da --source local   # same repositories from disk
uv run python -m evals.runners.portfolio_builder_eval
```

`--no-llm` writes template summaries without model calls. Repositories are read from
`portfolio_builder.owner`/`repo`/`ref`/`repos_path` in `agent/config.yaml`; here that is this
project's own public repository, where each folder under `data/personas/<persona>/repos` is one
project.
