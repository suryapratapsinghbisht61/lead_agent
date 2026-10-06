"""Per-lead step 3: write "About them", "How I can help" and a channel-specific message."""

from langgraph.runtime import Runtime

from app.agent.prompts import profile_text
from app.agent.prompts.outreach import CHANNEL_RULES, WRITE_OUTREACH
from app.agent.schemas import Channel, Lead, Outreach
from app.agent.state import LeadState, RunContext
from app.agent.utils import LLMQuotaExhausted, emit, structured_call


def pick_channel(lead: Lead) -> Channel:
    """Message them where we found them; for websites use their public email if we have it."""
    platform = lead.candidate.platform
    if platform == "reddit":
        return "reddit_dm"
    if platform == "linkedin":
        return "linkedin_note"
    if platform == "x":
        return "x_dm"
    return "email" if lead.public_email else "website_contact"


def signature(profile: dict) -> str:
    me = profile.get("me", {})
    parts = [me.get("name") or ""]
    if me.get("portfolio_url"):
        parts.append(me["portfolio_url"])
    return " | ".join(p for p in parts if p)


async def write_outreach(state: LeadState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    lead = state["lead"].model_copy(deep=True)
    c, q = lead.candidate, lead.qualification
    lead.channel = pick_channel(lead)

    messages = WRITE_OUTREACH.format_messages(
        profile=profile_text(ctx.profile),
        signature=signature(ctx.profile),
        channel_rule=CHANNEL_RULES[lead.channel],
        name=q.name or c.name,
        category=q.category,
        company=q.company or c.company or "unknown",
        platform=c.platform,
        signal=c.signal,
        pain_points="; ".join(q.pain_points) or "not specified",
        notes=lead.research_notes or c.signal,
    )
    try:
        out: Outreach = await structured_call(ctx.llm, Outreach, messages)
    except LLMQuotaExhausted:
        raise
    except Exception as e:
        return {"lead": lead, "errors": [f"write_outreach failed for {c.name}: {e}"]}

    if lead.channel != "email":
        out.subject = None
    sig = signature(ctx.profile)
    if sig and sig.split(" | ")[0] not in out.message:  # the LLM sometimes forgets to sign
        out.message = f"{out.message.rstrip()}\n{sig}"
    lead.outreach = out
    emit("write", f"Drafted {lead.channel} message for {c.name}")
    return {"lead": lead}


def finish_lead(state: LeadState) -> dict:
    """Hand the finished lead back to the main graph (appended to state['processed'])."""
    return {"processed": [state["lead"]]}
