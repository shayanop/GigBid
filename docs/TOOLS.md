# Tools

One row per MCP tool. Schemas are snapshotted in `tests/contract/snapshots/`; any change fails CI until the snapshot is regenerated on purpose.

## Marketplace MCP (`mcp_servers/marketplace`, owned by GigBid)

Transport: Streamable HTTP at `/mcp`. Auth: signed bearer token `<account>.<expiry>.<hmac>` (`MCP_SIGNING_SECRET`, see `mcp_servers/auth.py`); the API and worker mint a one-hour token per user. In-process/stdio use `MARKETPLACE_LOCAL_USER`. Every call is rate limited per user (`MARKETPLACE_RATE_PER_MIN`, default 60) and appended to the audit log with user, tool, redacted arguments, redacted result and trace ID (`X-Trace-Id` header, generated if absent). The adapter (GigSim now, Upwork later) comes from `marketplace.adapter` in `agent/config.yaml`.

| Tool | Permission | Annotations | Notes |
| --- | --- | --- | --- |
| `search_jobs` | read | readOnly, openWorld | keywords (all must match), skills (any), `posted_after`, `limit` ≤ 50 |
| `get_job` | read | readOnly, openWorld | full description and screening questions |
| `get_client_history` | read | readOnly, openWorld | spend, hire rate, rating, reviews, payment verified |
| `get_connects_balance` | read | readOnly, openWorld | |
| `list_messages` | read | readOnly, openWorld | all threads with messages |
| `create_proposal_draft` | write | idempotent, non-destructive, openWorld | needs `idempotency_key`; `dry_run` previews payload and Connects cost; spends nothing |
| `submit_proposal` | write | idempotent, **destructive**, openWorld | spends Connects; needs `idempotency_key`; `dry_run` previews cost and balance after |
| `send_message` | write | idempotent, non-destructive, openWorld | needs `idempotency_key`; `dry_run` previews |

Write tools are only called after human approval in GigBid (LangGraph interrupt). The server itself does not decide approval.

## Portfolio MCP (`mcp_servers/portfolio`, owned by GigBid)

Read-only. Transport: Streamable HTTP at `/mcp` (signed bearer token whose account names the persona folder) or stdio for external hosts (`--stdio`, persona from `PORTFOLIO_LOCAL_USER`). Retrieval variant comes from `rag.variant` in `agent/config.yaml`.

| Name | Kind | Permission | Annotations | Notes |
| --- | --- | --- | --- | --- |
| `search_evidence` | tool | read | readOnly, idempotent, closedWorld | `requirement`, `k` ≤ 20, `filters` (types, projects, outcomes, after); returns evidence with id, type, source, date, outcome, score |
| `get_case_study` | tool | read | readOnly, idempotent, closedWorld | full case study by project id |
| `list_skills` | tool | read | readOnly, idempotent, closedWorld | skills named in the portfolio with document counts and projects |
| `portfolio://case/{case_id}` | resource | read | | case study Markdown |
| `portfolio://proposal/{proposal_id}` | resource | read | | past proposal with outcome |
| `answer_screening_question` | prompt | | | answer a screening question from cited evidence only |

Claude Desktop config example (stdio; for HTTP, mint a token with `uv run python -m mcp_servers.auth fr_ml --days 30`):

```json
{"mcpServers": {"gigbid-portfolio": {"command": "uv", "args": ["--directory", "<repo>", "run",
  "python", "-m", "mcp_servers.portfolio.server", "--stdio"], "env": {"PORTFOLIO_LOCAL_USER": "fr_ml"}}}}
```

## Workspace MCP (`mcp_servers/workspace`, owned by GigBid)

Calendar and email drafts for the freelancer, backed by a local mock calendar per account (`WORKSPACE_DIR`); Google Calendar and Gmail can replace it behind the same tools. Times are UTC. Auth as above; in-process/stdio use `WORKSPACE_LOCAL_USER`.

| Tool | Permission | Annotations | Notes |
| --- | --- | --- | --- |
| `find_free_slots` | read | readOnly, idempotent, closedWorld | weekday slots, at most one per day; duration, days ahead, working hours, limit |
| `hold_slot` | write | idempotent, non-destructive, closedWorld | tentative event; needs `idempotency_key`; refuses times that are no longer free |
| `create_email_draft` | write | idempotent, non-destructive, closedWorld | saved for the freelancer to send; needs `idempotency_key` |

The Client Liaison offers `find_free_slots` results to clients and calls `hold_slot` only after the reply is approved and sent.

## Third-party servers

### GitHub MCP (GitHub's official server, not owned by GigBid)

Used by the portfolio builder (signature extension X3, [EXTENSION.md](EXTENSION.md)) to read the freelancer's repositories. It is not used inside the bid or conversation graphs. Endpoint: GitHub's hosted server, `https://api.githubcopilot.com/mcp/` (`portfolio_builder.github_mcp_url`), over Streamable HTTP. Auth: a GitHub personal access token in `GITHUB_TOKEN`, sent as a bearer token to that host only and never logged.

| Tool | Permission | Annotations | Notes |
| --- | --- | --- | --- |
| `get_file_contents` | read | readOnly (GitHub's) | `owner`, `repo`, `path`, `ref`. A folder returns a JSON listing; a file returns a status line plus the file as an embedded resource. The only GitHub tool on the allowlist (`portfolio_builder` in `agent/mcp_client.py`). |

**Trust rationale.**
- **Who maintains it.** GitHub maintains the server (`github/github-mcp-server`, open source), and it sits in front of GitHub's own API. No community proxy sits between GigBid and the data.
- **Least privilege.** Create a fine-grained token with read-only *Contents* access to the portfolio repositories only. The allowlist exposes one read tool, so nothing can write to GitHub even if the token could.
- **Untrusted content.** Repository text is treated as untrusted data. Code is only scanned with regular expressions and never executed or imported. The README reaches the model fenced as untrusted, and the prompt says to ignore instructions in it.
- **Verified output.** Every skill in a generated case study must match a line of code; summary sentences naming any other skill are dropped before indexing.
- **Failure isolation.** The builder runs as an offline batch job. If GitHub is down or rate-limited, the existing index is untouched and agents keep working.

The official Upwork MCP server (live marketplace mode) is not integrated yet.

## Tool granularity experiment (A7)

Research question A: does the shape of the tool set change what the agent calls?
[`evals/runners/tool_granularity.py`](../evals/runners/tool_granularity.py) sends 40
requests with known correct calls ([`tool_tasks.jsonl`](../evals/datasets/tool_tasks.jsonl),
written by hand) to `gpt-oss-120b` on Cerebras, at temperature 0, with three tool sets:

- **Fine:** the eight read-only tools above, as the servers describe them.
- **Coarse:** two tools, `marketplace(action, ...)` and `portfolio(action, ...)`.
- **Tuned:** the fine tools with descriptions that say when to use each one and with what.

Each request gets one model turn. The calls it makes are scored without being run.
Selection is right when the tools called match the expected ones. An argument is right when
an id matches exactly, or when free text contains the expected keywords. A request whose
second call needs the first one's result (a client id from a job) expects only the first.
Results: [`tool_granularity.md`](../evals/results/tool_granularity.md).

| Tool set | Tools | Selection accuracy | Argument accuracy | Tokens per task |
| --- | --- | --- | --- | --- |
| Fine | 8 | 0.925 | 0.930 | 620 |
| Coarse | 2 | 0.875 | 0.884 | 420 |
| Tuned | 8 | 0.900 | 0.907 | 671 |

- **Missed second call (all three sets).** All three sets miss the same three requests,
  each of which needs two independent calls ("find evidence for both Stripe payments and
  Celery"). The model makes only the first, although the system prompt asks for
  independent calls together. Granularity does not cause this one-call-per-turn habit.
  The bid graph avoids it by issuing its parallel searches in code (`agent/nodes/matcher.py`).
- **Coarse.** The coarse set saves about a third of the tokens, because two schemas are
  shorter than eight. It costs two more errors: "how much has cl_0181 spent" went to
  `action: connects`, and "past proposals mentioning fine-tuning" went to `messages`.
  An `action` enum hides the distinctions that separate tool names carry.
- **Tuned.** One tuned description made things worse. `list_messages` now mentions "new
  replies to proposals", which pulled the "past proposals" request to it. The tuned set
  changed nothing else, and the fine descriptions stay.
- **Noise.** Each task is 2.5 points, and the sets differ by one or two tasks in a single
  run, so none of the differences is statistically meaningful. The finding that holds is the
  shared failure on independent multi-call requests.

The deployed tool set stays fine-grained with the original descriptions.
