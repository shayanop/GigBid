"""Portfolio MCP server (A1): read-only evidence search over a freelancer's portfolio.

Serves GigBid's agents over Streamable HTTP (bearer token -> persona folder) and
external hosts such as Claude Desktop or Cursor over stdio, where
PORTFOLIO_LOCAL_USER names the persona folder (e.g. fr_ml).

Run: python -m mcp_servers.portfolio.server [--stdio]
"""

import asyncio
import os
import re
import sys
from collections import defaultdict
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from gigsim.seed import mentioned_skills
from mcp_servers.auth import bearer_auth, current_user
from rag import retriever
from rag.ingest.loaders import SKILLS, load_persona
from rag.schema import Chunk, DocType, Document, Evidence

READ = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
Id = Annotated[str, Field(pattern=r"^[\w-]{1,64}$")]

URL = os.getenv("PORTFOLIO_MCP_URL", "http://localhost:8300/mcp")
mcp = MCPServer(
    "gigbid-portfolio",
    instructions="Read-only access to one freelancer's portfolio: CV, case studies, code, "
                 "client reviews and past proposals with outcomes. Every claim in a proposal "
                 "should cite an evidence id returned by search_evidence.",
    **bearer_auth(URL),
)


class EvidenceFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    types: list[DocType] | None = None
    projects: list[Id] | None = None
    outcomes: list[Literal["won", "replied", "ignored"]] | None = None
    after: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None

    def matches(self, c: Chunk) -> bool:
        return ((self.types is None or c.type in self.types)
                and (self.projects is None or c.project in self.projects)
                and (self.outcomes is None or c.outcome in self.outcomes)
                and (self.after is None or (c.date or "") > self.after))


class SkillEvidence(BaseModel):
    skill: str
    documents: int
    projects: list[str]


def _persona() -> str:
    persona = current_user("PORTFOLIO")
    if not re.fullmatch(r"[\w-]{1,64}", persona) or not (retriever.PERSONAS_DIR / persona).is_dir():
        raise ToolError(f"no portfolio for {persona!r}")
    return persona


def _document(doc_id: str, doc_type: DocType) -> Document:
    for doc in load_persona(retriever.PERSONAS_DIR / _persona()):
        if doc.id == doc_id and doc.type == doc_type:
            return doc
    raise ToolError(f"{doc_type} {doc_id!r} not found")


@mcp.tool(annotations=READ)
async def search_evidence(
    requirement: Annotated[str, Field(min_length=3, max_length=2000, description=(
        "One job requirement or the job text, e.g. 'background jobs with Celery'"))],
    k: Annotated[int, Field(ge=1, le=20)] = 5,
    filters: EvidenceFilters | None = None,
) -> list[Evidence]:
    """Find portfolio evidence for a job requirement: case studies, code, reviews and past
    proposals (with outcomes), best match first. Each result has an id to cite."""
    persona, where = _persona(), filters.matches if filters else None
    # First call builds the index (model load + embedding), so keep it off the event loop.
    return await asyncio.to_thread(
        lambda: retriever.get_retriever(persona).search(requirement, k, where))


@mcp.tool(annotations=READ)
async def get_case_study(case_id: Id) -> Document:
    """Get the full text and metadata of one case study (its id is its project id)."""
    return _document(case_id, "case_study")


@mcp.tool(annotations=READ)
async def list_skills() -> list[SkillEvidence]:
    """List skills named anywhere in the portfolio, with how many documents and which
    projects mention each. Skills only implied by the work are not listed."""
    docs, projects = defaultdict(int), defaultdict(set)
    for doc in load_persona(retriever.PERSONAS_DIR / _persona()):
        for skill in mentioned_skills(doc.text, SKILLS):
            docs[skill] += 1
            if doc.project:
                projects[skill].add(doc.project)
    return [SkillEvidence(skill=s, documents=n, projects=sorted(projects[s]))
            for s, n in sorted(docs.items(), key=lambda kv: -kv[1])]


@mcp.resource("portfolio://case/{case_id}", mime_type="text/markdown")
def case_resource(case_id: str) -> str:
    """Full case study document."""
    return _document(case_id, "case_study").text


@mcp.resource("portfolio://proposal/{proposal_id}", mime_type="text/plain")
def proposal_resource(proposal_id: str) -> str:
    """A past proposal with its outcome (won, replied or ignored)."""
    doc = _document(proposal_id, "proposal")
    return f"Outcome: {doc.outcome}\nDate: {doc.date}\nProject: {doc.project}\n\n{doc.text}"


@mcp.prompt()
def answer_screening_question(question: str) -> str:
    """Answer a client's screening question from my portfolio only."""
    return (f"Answer this client screening question in 2-4 sentences:\n\n{question}\n\n"
            "Call search_evidence first. Use only facts from the returned evidence and cite "
            "each fact with its evidence id in brackets. If the evidence does not support an "
            "answer, say what you have not done rather than inventing experience.")


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run("stdio")
    else:
        # Index before listening: a cold first search would outlast agents' tool timeouts.
        print(f"portfolio indexes ready: {', '.join(retriever.warm_all())}", flush=True)
        mcp.run("streamable-http", host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", "8300")))
