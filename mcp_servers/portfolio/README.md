# GigBid Portfolio MCP server

A read-only MCP server over a freelancer's portfolio: CV, case studies, code, client reviews
and past proposals with their outcomes. Use it from Claude Desktop, Cursor or any MCP host
to answer screening questions and draft proposals, citing only evidence that exists.
Inside GigBid it is the only way agents see the portfolio.

## Tools

All tools are read-only and idempotent.

| Tool | What it returns |
| --- | --- |
| `search_evidence(requirement, k=5, filters?)` | The best-matching evidence for one requirement. Each result has an `id` to cite. The retriever is hybrid BM25 + dense search with an outcome prior; see [docs/RAG_STUDY.md](../../docs/RAG_STUDY.md) for why. |
| `get_case_study(case_id)` | One case study in full, with its metadata. |
| `list_skills()` | Every skill named in the portfolio, with document counts and the projects that mention it. |

There is also one prompt, `answer_screening_question`. Full schemas are in
[docs/TOOLS.md](../../docs/TOOLS.md).

## Your portfolio folder

Make one folder per freelancer (its name is the account, e.g. `sana`) inside a parent
folder. Every part is optional:

```text
portfolios/
  sana/
    cv.pdf
    case_studies/<project-id>.md   # "Client industry:" and "Completed: YYYY-MM-DD" lines are read
    repos/<project-id>/<file>      # README.md and code files
    reviews.jsonl                  # {"id", "project", "date", "rating", "text"} per line
    proposals.jsonl                # {"id", "project", "job_title", "date", "outcome", "text"}
```

The bundled synthetic personas in `data/personas/` show the format.

## Run with Docker

Build the GigBid image once from the repository root. The image bakes the embedding model
and the bundled personas' indexes in.

```bash
docker build -f infra/docker/python.Dockerfile -t gigbid .
```

**Over stdio,** for Claude Desktop, Cursor or another local host. Mount your folder and
name the account:

```json
{
  "mcpServers": {
    "gigbid-portfolio": {
      "command": "docker",
      "args": ["run", "-i", "--rm",
               "-v", "/path/to/portfolios:/portfolios:ro",
               "-e", "PORTFOLIO_DIR=/portfolios",
               "-e", "PORTFOLIO_INDEX_DIR=/tmp/index",
               "-e", "PORTFOLIO_LOCAL_USER=sana",
               "gigbid", "python", "-m", "mcp_servers.portfolio.server", "--stdio"]
    }
  }
}
```

Leave out the `-v`, `PORTFOLIO_DIR` and `PORTFOLIO_INDEX_DIR` lines and set
`PORTFOLIO_LOCAL_USER` to `fr_ml`, `fr_fs` or `fr_da` to try the bundled personas.

**Over Streamable HTTP,** for remote hosts and GigBid's own agents. Every request needs a
signed bearer token naming the account.

```bash
docker run --rm -p 8300:8300 -e HOST=0.0.0.0 -e MCP_SIGNING_SECRET=<a long random secret> \
  -e PORTFOLIO_MCP_URL=http://localhost:8300/mcp \
  gigbid python -m mcp_servers.portfolio.server
```

Mint a token with the same secret, one per account:

```bash
MCP_SIGNING_SECRET=<the same secret> uv run python -m mcp_servers.auth fr_ml --days 30
```

Send it as `Authorization: Bearer <token>`. A token only ever reads its own account's
folder.

## Run from source

```bash
uv sync
PORTFOLIO_LOCAL_USER=fr_ml uv run python -m mcp_servers.portfolio.server --stdio
```

## Behaviour

- **Read only.** It never writes outside its index folder (`PORTFOLIO_INDEX_DIR`).
- **First search.** The first search for an account builds that account's index, which
  takes seconds to minutes depending on size. The HTTP server builds every index before it
  listens.
- **Untrusted text.** Portfolio text is returned as data. Hosts should treat it as
  untrusted, and GigBid's agents fence it before it reaches a model.
- **Optional extension.** GitHub repositories can be turned into code-verified case
  studies by the portfolio builder ([docs/EXTENSION.md](../../docs/EXTENSION.md)).

Tests: `uv run pytest mcp_servers/portfolio/tests`.
