"""Portfolio documents, chunks and evidence shared by ingestion, retrieval and MCP."""

from typing import Literal

from pydantic import BaseModel

DocType = Literal["cv", "case_study", "repo_readme", "code", "review", "proposal"]


class Document(BaseModel):
    id: str
    persona: str
    type: DocType
    source: str  # path inside the persona folder, "#row" for JSONL records
    project: str | None = None
    date: str | None = None
    client_industry: str | None = None
    outcome: Literal["won", "replied", "ignored"] | None = None
    text: str


class Chunk(Document):
    doc_id: str
    skills: list[str]  # skills named in this chunk's text


class Evidence(Chunk):
    score: float
