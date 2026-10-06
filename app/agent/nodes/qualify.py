"""Per-lead step 2: categorise, find pain points, score fit 1-10 (structured output)."""

from datetime import date

from langgraph.runtime import Runtime

from app.agent.prompts import profile_text
from app.agent.prompts.qualify import QUALIFY
from app.agent.schemas import Qualification
from app.agent.state import LeadState, RunContext
from app.agent.utils import LLMQuotaExhausted, emit, structured_call


async def qualify(state: LeadState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    lead = state["lead"].model_copy(deep=True)
    if lead.skipped_reason:
        return {}
    c = lead.candidate

    messages = QUALIFY.format_messages(
        profile=profile_text(ctx.profile),
        today=date.today().isoformat(),
        name=c.name,
        platform=c.platform,
        company=c.company or "unknown",
        signal=c.signal,
        source_url=c.source_url,
        notes=lead.research_notes or c.signal,
    )
    try:
        lead.qualification = await structured_call(ctx.llm, Qualification, messages)
    except LLMQuotaExhausted:
        raise
    except Exception as e:
        return {"lead": lead, "errors": [f"qualify failed for {c.name}: {e}"]}

    q = lead.qualification
    if q.category not in state["params"].categories:
        lead.skipped_reason = f"category '{q.category}' not requested"
    emit("qualify", f"{c.name}: {q.category}, fit {q.fit_score}/10 ({q.fit_reason})")
    return {"lead": lead}


def route_after_qualify(state: LeadState, runtime: Runtime[RunContext]) -> str:
    """Only write outreach for leads that are worth contacting (saves LLM calls)."""
    lead = state["lead"]
    q = lead.qualification
    if lead.skipped_reason or q is None or q.fit_score < runtime.context.min_fit_score:
        return "finish_lead"
    return "write_outreach"
