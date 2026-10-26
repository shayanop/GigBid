"""Request and response schemas. The web client is generated from the OpenAPI they produce."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from agent.handoffs import (
    BidDecision,
    ClaimReport,
    ComplianceVerdict,
    Critique,
    FitReport,
    JobSpec,
    PriceQuote,
    ProposalDraft,
    RiskReport,
)

Account = Annotated[str, Field(pattern=r"^[\w-]{1,64}$")]
JobId = Annotated[str, Field(pattern=r"^[\w-]{1,64}$")]


class Credentials(BaseModel):
    email: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)]
    password: Annotated[str, Field(min_length=12, max_length=128)]


class Signup(Credentials):
    account: Account = Field(description="Marketplace account (GigSim: fr_ml, fr_fs, fr_da)")


class Settings(BaseModel):
    hourly_rate_floor: Annotated[float, Field(ge=0)] | None = None
    weekly_connects_budget: Annotated[int, Field(ge=0)] | None = None


class UserOut(BaseModel):
    id: UUID
    email: str
    account: str
    settings: Settings


class SearchIn(BaseModel):
    query: Annotated[str, Field(max_length=200)] = ""
    skills: Annotated[list[str], Field(max_length=10)] = []
    every_minutes: Annotated[int, Field(ge=15, le=1440)] = 60


class SearchOut(SearchIn):
    id: UUID
    enabled: bool
    last_run_at: datetime | None


class AnalyzeIn(BaseModel):
    job_id: JobId


class JobSummary(BaseModel):
    thread_id: UUID
    job_id: str
    title: str
    status: str
    decision: str | None = None
    fit: float | None = None
    risk: float | None = None
    flags: list[str] = []
    price: float | None = None
    connects_cost: int | None = None
    attention: str | None = None
    updated_at: datetime


class EvidenceOut(BaseModel):
    id: str
    type: str
    source: str
    project: str | None
    date: str | None
    outcome: str | None
    text: str


class JobDetail(JobSummary):
    spec: JobSpec | None = None
    risk_report: RiskReport | None = None
    fit_report: FitReport | None = None
    decision_detail: BidDecision | None = None
    evidence: list[EvidenceOut] = []
    price_quote: PriceQuote | None = None
    draft: ProposalDraft | None = None
    claims: ClaimReport | None = None
    critique: Critique | None = None
    compliance: ComplianceVerdict | None = None


class ApprovalRequest(BaseModel):
    """What the human sees before anything is sent: the interrupt payload."""
    thread_id: UUID
    title: str
    request: dict


class Accepted(BaseModel):
    thread_id: UUID
    status: str


class TraceOut(BaseModel):
    status: str | None
    usage: dict
    trace: list[dict]
