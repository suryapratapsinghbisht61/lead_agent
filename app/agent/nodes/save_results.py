"""Final node: save leads to the database and write the Excel export."""

from langgraph.runtime import Runtime

from app.agent.state import AgentState, RunContext
from app.agent.utils import emit
from app.core.config import get_settings
from app.db import repo
from app.services.export import leads_to_xlsx


def save_results(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    processed = state.get("processed", [])
    records = repo.save_leads(ctx.run_id, processed, ctx.min_fit_score)
    qualified = [r for r in records if not r.low_fit and r.message]

    export_path = None
    if qualified:
        export_dir = get_settings().export_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"leads_{ctx.run_id}.xlsx"
        path.write_bytes(leads_to_xlsx(sorted(qualified, key=lambda r: -r.fit_score)))
        export_path = str(path)

    summary = {
        "qualified": len(qualified),
        "low_fit_saved": len(records) - len(qualified),
        "processed": len(processed),
        "skipped": sum(1 for lead in processed if lead.skipped_reason),
        "lead_ids": [r.id for r in qualified],
        "export_path": export_path,
        "stop_reason": state.get("stop_reason", ""),
    }
    emit("save", f"Saved {len(records)} leads ({len(qualified)} qualified)")
    return {"summary": summary}
