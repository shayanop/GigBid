"""The single marketplace interface (R1). GigSim and Upwork adapters implement
MarketplacePort; the Marketplace MCP server picks one from agent/config.yaml."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Job(BaseModel):
    id: str
    title: str
    description: str
    skills: list[str]
    budget_type: Literal["fixed", "hourly"]
    budget_min: float | None
    budget_max: float | None
    posted_at: datetime
    connects_cost: int
    client_id: str
    screening_questions: list[str] = []


class JobPage(BaseModel):
    total: int
    jobs: list[Job]


class Client(BaseModel):
    id: str
    name: str
    country: str
    payment_verified: bool
    total_spend: float
    hire_rate: float
    jobs_posted: int
    rating: float | None
    reviews: list[str]
    member_since: datetime


class Message(BaseModel):
    id: str
    sender: Literal["client", "freelancer"]
    body: str
    sent_at: datetime


class Thread(BaseModel):
    id: str
    job_id: str
    client_id: str
    messages: list[Message]


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1, max_length=5000)
    screening_answers: list[str] = Field(default=[], max_length=10)
    bid_amount: float = Field(gt=0, le=1_000_000)


class Proposal(ProposalIn):
    id: str
    status: Literal["draft", "submitted"]
    connects_cost: int
    created_at: datetime
    submitted_at: datetime | None


class MarketplaceError(Exception):
    """A request the marketplace refused (not found, insufficient Connects, ...)."""


class MarketplaceUnavailable(MarketplaceError):
    """The marketplace is down or rate limiting after retries; work is recoverable."""


class MarketplacePort(Protocol):
    async def search_jobs(self, query: str, skills: list[str], posted_after: datetime | None,
                          limit: int, offset: int) -> JobPage: ...
    async def get_job(self, job_id: str) -> Job: ...
    async def get_client(self, client_id: str) -> Client: ...
    async def get_connects(self) -> int: ...
    async def list_threads(self) -> list[Thread]: ...
    async def get_proposal(self, proposal_id: str) -> Proposal: ...
    async def create_proposal_draft(self, draft: ProposalIn, idempotency_key: str) -> Proposal: ...
    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> Proposal: ...
    async def send_message(self, thread_id: str, body: str, idempotency_key: str) -> Message: ...
