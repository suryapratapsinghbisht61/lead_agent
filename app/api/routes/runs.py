"""/runs endpoints: start a run, watch it, get its leads, download Excel."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.agent.runner import new_run_id
from app.agent.schemas import RunParams
from app.api.deps import get_redis, rate_limited, run_rate_limited
from app.api.schemas import RunCreated, RunOut
from app.db import repo
from app.db.models import LeadRecord, Run
from app.services.export import leads_to_xlsx
from app.services.jobs import get_progress

router = APIRouter(prefix="/runs", tags=["runs"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _get_run_or_404(run_id: str) -> Run:
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


@router.post("", response_model=RunCreated, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(run_rate_limited)])
async def start_run(params: RunParams, request: Request) -> RunCreated:
    """Queue a new agent run. Returns immediately; poll GET /runs/{run_id} for progress."""
    run_id = new_run_id()
    repo.create_run(run_id, params.model_dump())
    await get_redis(request).enqueue_job("run_agent_job", run_id, params.model_dump(), _job_id=run_id)
    return RunCreated(run_id=run_id, status="queued")


@router.get("", response_model=list[Run], dependencies=[Depends(rate_limited)])
def list_runs(limit: int = 50) -> list[Run]:
    return repo.list_runs(limit)


@router.get("/{run_id}", response_model=RunOut, dependencies=[Depends(rate_limited)])
async def get_run(run_id: str, request: Request) -> RunOut:
    run = _get_run_or_404(run_id)
    live = await get_progress(get_redis(request), run_id) if run.status in ("queued", "running") else None
    return RunOut(run=run, live_progress=live)


@router.get("/{run_id}/events", dependencies=[Depends(rate_limited)])
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events: a live progress stream for a frontend (EventSource)."""
    _get_run_or_404(run_id)
    redis = get_redis(request)

    async def stream():
        last = None
        while not await request.is_disconnected():
            run = repo.get_run(run_id)
            progress = await get_progress(redis, run_id) or {"message": run.progress}
            payload = json.dumps({"status": run.status, **progress})
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if run.status in ("completed", "failed"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/{run_id}/leads", response_model=list[LeadRecord], dependencies=[Depends(rate_limited)])
def run_leads(run_id: str, include_low_fit: bool = False) -> list[LeadRecord]:
    _get_run_or_404(run_id)
    leads, _ = repo.list_leads(run_id=run_id, include_low_fit=include_low_fit, limit=1000)
    return leads


@router.get("/{run_id}/export.xlsx", dependencies=[Depends(rate_limited)],
            responses={200: {"content": {XLSX: {}}}})
def export_run(run_id: str) -> Response:
    _get_run_or_404(run_id)
    leads, _ = repo.list_leads(run_id=run_id, limit=1000)
    return Response(leads_to_xlsx(leads), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="leads_{run_id}.xlsx"'})
