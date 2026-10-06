"""Request/response shapes for the API (these also generate the /docs page)."""

from datetime import datetime

from pydantic import BaseModel

from app.db.models import LeadRecord, Run


class RunCreated(BaseModel):
    run_id: str
    status: str


class RunOut(BaseModel):
    run: Run
    live_progress: dict | None = None  # latest event from Redis while the run is going


class LeadPage(BaseModel):
    items: list[LeadRecord]
    total: int
    page: int
    page_size: int


class LeadUpdate(BaseModel):
    status: str | None = None  # new | sent | replied | meeting | closed
    notes: str | None = None


class Health(BaseModel):
    status: str
    database: bool
    redis: bool
    llm: str
    time: datetime
