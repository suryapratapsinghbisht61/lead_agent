"""/leads endpoints: browse, filter, update outreach status, export."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import rate_limited
from app.api.schemas import LeadPage, LeadUpdate
from app.db import repo
from app.db.models import LeadRecord
from app.services.export import leads_to_xlsx

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(rate_limited)])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class LeadFilters:
    """Query parameters shared by GET /leads and GET /leads/export.xlsx."""

    def __init__(
        self,
        category: list[str] | None = Query(None, description="startup / company / individual (repeatable)"),
        platform: list[str] | None = Query(None, description="reddit / linkedin / x / web (repeatable)"),
        status: list[str] | None = Query(None, description="new / sent / replied / meeting / closed"),
        min_score: int | None = Query(None, ge=1, le=10),
        include_low_fit: bool = False,
        q: str | None = Query(None, description="search in name, company, signal"),
    ):
        self.kwargs = dict(categories=category, platforms=platform, statuses=status, min_score=min_score,
                           include_low_fit=include_low_fit, search=q)


@router.get("", response_model=LeadPage)
def list_leads(filters: LeadFilters = Depends(), page: int = Query(1, ge=1),
               page_size: int = Query(50, ge=1, le=500)) -> LeadPage:
    items, total = repo.list_leads(**filters.kwargs, offset=(page - 1) * page_size, limit=page_size)
    return LeadPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/export.xlsx", responses={200: {"content": {XLSX: {}}}})
def export_leads(filters: LeadFilters = Depends()) -> Response:
    items, _ = repo.list_leads(**filters.kwargs, limit=100_000)
    return Response(leads_to_xlsx(items), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="leads.xlsx"'})


@router.get("/{lead_id}", response_model=LeadRecord)
def get_lead(lead_id: int) -> LeadRecord:
    lead = repo.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadRecord)
def update_lead(lead_id: int, body: LeadUpdate) -> LeadRecord:
    try:
        lead = repo.update_lead(lead_id, status=body.status, notes=body.notes)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead
