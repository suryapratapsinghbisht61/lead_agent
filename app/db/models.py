"""Database tables (SQLModel = Pydantic models that are also SQL tables).

runs      one row per agent run (params, status, progress, credits)
leads     one row per lead ever found (qualified AND low-fit), plus outreach status
lead_keys every dedupe key (profile URL, handle, domain) -> lead. This is how we
          guarantee the same person/company never comes back in a later run.
api_keys  hashed API keys for the FastAPI server
"""

from datetime import datetime, timezone

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel

OUTREACH_STATUSES = ["new", "sent", "replied", "meeting", "closed"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(primary_key=True)
    status: str = Field(default="queued", index=True)  # queued | running | completed | failed
    params: dict = Field(default_factory=dict, sa_type=JSON)
    progress: str = ""  # latest human-readable progress line
    qualified_count: int = 0
    processed_count: int = 0
    credits_used: int = 0
    cost_usd: float = 0.0
    errors: list = Field(default_factory=list, sa_type=JSON)
    stop_reason: str | None = None
    export_path: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LeadRecord(SQLModel, table=True):
    __tablename__ = "leads"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", index=True)

    # who
    name: str
    handle: str | None = None
    profile_url: str | None = None
    company: str | None = None
    company_website: str | None = None
    public_email: str | None = None
    platform: str = Field(index=True)
    category: str | None = Field(default=None, index=True)

    # why
    signal: str = ""
    source_url: str = ""
    pain_points: list = Field(default_factory=list, sa_type=JSON)
    fit_score: int = Field(default=0, index=True)
    fit_reason: str = ""
    low_fit: bool = Field(default=False, index=True)

    # outreach draft
    about_them: str = ""
    how_i_can_help: str = ""
    channel: str | None = None
    subject: str | None = None
    message: str = ""

    # your tracking
    status: str = Field(default="new", index=True)  # see OUTREACH_STATUSES
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LeadKey(SQLModel, table=True):
    __tablename__ = "lead_keys"

    key: str = Field(primary_key=True)  # e.g. "profile:linkedin.com/in/jane-doe", "domain:acme.com"
    lead_id: int = Field(foreign_key="leads.id", index=True)


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    key_hash: str = Field(index=True, unique=True)  # sha256 of the key; the key itself is never stored
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
