"""All database reads/writes in one place, so nodes, CLI, dashboard and API share them."""

import hashlib
import secrets
from datetime import timedelta

from sqlmodel import col, func, select

from app.agent.schemas import Lead
from app.db.models import OUTREACH_STATUSES, ApiKey, LeadKey, LeadRecord, Run, utcnow
from app.db.session import get_session


# ------------------------------------------------------------------ runs
def create_run(run_id: str, params: dict) -> Run:
    with get_session() as s:
        run = Run(id=run_id, params=params)
        s.add(run)
        s.commit()
        return run


def update_run(run_id: str, **fields) -> None:
    with get_session() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        for k, v in fields.items():
            setattr(run, k, v)
        s.add(run)
        s.commit()


def fail_stale_runs(max_hours: float = 1.0) -> int:
    """Mark runs stuck in "running" for longer than max_hours as failed.

    A run whose process was killed (server restart, out of memory) never gets to
    record its outcome, so it would show as running forever.
    """
    cutoff = utcnow() - timedelta(hours=max_hours)
    with get_session() as s:
        stale = list(s.exec(select(Run).where(Run.status == "running", col(Run.started_at) < cutoff)))
        for run in stale:
            run.status = "failed"
            run.finished_at = utcnow()
            run.progress = f"Interrupted: the app stopped during the run (last step: {run.progress})"
            run.errors = [*(run.errors or []), "interrupted"]
            s.add(run)
        s.commit()
        return len(stale)


def get_run(run_id: str) -> Run | None:
    with get_session() as s:
        return s.get(Run, run_id)


def list_runs(limit: int = 50) -> list[Run]:
    with get_session() as s:
        return list(s.exec(select(Run).order_by(col(Run.created_at).desc()).limit(limit)))


# ------------------------------------------------------------------ dedup
def existing_keys(keys: list[str]) -> set[str]:
    """Which of these dedupe keys belong to a lead saved in a previous run?"""
    if not keys:
        return set()
    with get_session() as s:
        return set(s.exec(select(LeadKey.key).where(col(LeadKey.key).in_(keys))))


# ------------------------------------------------------------------ leads
def lead_to_record(run_id: str, lead: Lead, min_score: int) -> LeadRecord:
    c, q, o = lead.candidate, lead.qualification, lead.outreach
    score = q.fit_score if q else 0
    return LeadRecord(
        run_id=run_id,
        name=(q.name if q and q.name else None) or c.name,
        handle=c.handle,
        profile_url=c.profile_url,
        company=(q.company if q and q.company else None) or c.company,
        company_website=c.company_website,
        public_email=lead.public_email,
        platform=c.platform,
        category=q.category if q else None,
        signal=c.signal,
        source_url=c.source_url,
        pain_points=q.pain_points if q else [],
        fit_score=score,
        fit_reason=q.fit_reason if q else "",
        low_fit=score < min_score,
        about_them=o.about_them if o else "",
        how_i_can_help=o.how_i_can_help if o else "",
        channel=lead.channel,
        subject=o.subject if o else None,
        message=o.message if o else "",
    )


def save_leads(run_id: str, leads: list[Lead], min_score: int) -> list[LeadRecord]:
    """Save qualified and low-fit leads with all their dedupe keys.
    NOT saved: skipped leads (duplicates), leads that failed qualification, and good leads
    whose message failed to generate. Those can be found again in a future run."""
    saved: list[LeadRecord] = []
    with get_session() as s:
        for lead in leads:
            if lead.skipped_reason or lead.qualification is None:
                continue
            if lead.qualification.fit_score >= min_score and lead.outreach is None:
                continue  # good lead but no message (LLM error): retry it in a later run
            keys = list(dict.fromkeys(lead.dedupe_keys))
            if any(s.get(LeadKey, k) is not None for k in keys):
                continue  # already saved (e.g. by another run that finished at the same time)
            record = lead_to_record(run_id, lead, min_score)
            s.add(record)
            s.flush()  # assigns record.id
            for k in keys:
                s.add(LeadKey(key=k, lead_id=record.id))
            saved.append(record)
        s.commit()
    return saved


def list_leads(
    run_id: str | None = None,
    categories: list[str] | None = None,
    platforms: list[str] | None = None,
    statuses: list[str] | None = None,
    min_score: int | None = None,
    include_low_fit: bool = False,
    search: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[LeadRecord], int]:
    """Filtered, paginated leads (newest + best first). Returns (rows, total_count)."""
    q = select(LeadRecord)
    if run_id:
        q = q.where(LeadRecord.run_id == run_id)
    if categories:
        q = q.where(col(LeadRecord.category).in_(categories))
    if platforms:
        q = q.where(col(LeadRecord.platform).in_(platforms))
    if statuses:
        q = q.where(col(LeadRecord.status).in_(statuses))
    if min_score is not None:
        q = q.where(LeadRecord.fit_score >= min_score)
    if not include_low_fit:
        q = q.where(LeadRecord.low_fit == False)  # noqa: E712  (SQL comparison, not Python)
    if search:
        like = f"%{search}%"
        q = q.where(col(LeadRecord.name).ilike(like) | col(LeadRecord.company).ilike(like)
                    | col(LeadRecord.signal).ilike(like))
    with get_session() as s:
        total = s.exec(select(func.count()).select_from(q.subquery())).one()
        rows = s.exec(
            q.order_by(col(LeadRecord.created_at).desc(), col(LeadRecord.fit_score).desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows), total


def get_lead(lead_id: int) -> LeadRecord | None:
    with get_session() as s:
        return s.get(LeadRecord, lead_id)


def update_lead(lead_id: int, status: str | None = None, notes: str | None = None) -> LeadRecord | None:
    if status is not None and status not in OUTREACH_STATUSES:
        raise ValueError(f"status must be one of {OUTREACH_STATUSES}")
    with get_session() as s:
        lead = s.get(LeadRecord, lead_id)
        if lead is None:
            return None
        if status is not None:
            lead.status = status
        if notes is not None:
            lead.notes = notes
        lead.updated_at = utcnow()
        s.add(lead)
        s.commit()
        return lead


# ------------------------------------------------------------------ API keys
def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(name: str) -> str:
    """Create a key and return it ONCE. Only its hash is stored."""
    raw = "la_" + secrets.token_urlsafe(32)
    with get_session() as s:
        s.add(ApiKey(name=name, key_hash=hash_key(raw)))
        s.commit()
    return raw


def find_api_key(raw_key: str) -> ApiKey | None:
    with get_session() as s:
        return s.exec(select(ApiKey).where(ApiKey.key_hash == hash_key(raw_key), ApiKey.active == True)).first()  # noqa: E712


def list_api_keys() -> list[ApiKey]:
    with get_session() as s:
        return list(s.exec(select(ApiKey)))


def revoke_api_key(key_id: int) -> bool:
    with get_session() as s:
        key = s.get(ApiKey, key_id)
        if key is None:
            return False
        key.active = False
        s.add(key)
        s.commit()
        return True
