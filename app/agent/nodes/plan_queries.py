"""Node 1: turn the user's request into Google search queries, per platform."""

import logging

from langgraph.runtime import Runtime

from app.agent.prompts import profile_text
from app.agent.prompts.plan_queries import PLAN_QUERIES
from app.agent.schemas import QueryPlan, RunParams, SearchQuery
from app.agent.state import AgentState, RunContext
from app.agent.utils import LLMQuotaExhausted, emit, structured_call

log = logging.getLogger(__name__)


def fallback_queries(profile: dict, params: RunParams, round_no: int, per_platform: int) -> list[SearchQuery]:
    """If the LLM fails, build simple queries straight from the pain signals in services.yaml."""
    signals = profile.get("pain_signals") or ["need help automating"]
    extra = " ".join(filter(None, [params.niche, *params.keywords]))
    queries = []
    for platform in params.platforms:
        for i in range(per_platform):
            signal = signals[(round_no * per_platform + i) % len(signals)]
            queries.append(SearchQuery(platform=platform, query=f'"{signal}" {extra}'.strip(), reason="fallback"))
    return queries


async def plan_queries(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    params = state["params"]
    round_no = state.get("round", 0) + 1
    past = state.get("past_queries", [])
    per_platform = 3 if round_no == 1 else 2
    emit("plan", f"Round {round_no}: planning search queries")

    errors: list[str] = []
    messages = PLAN_QUERIES.format_messages(
        profile=profile_text(ctx.profile),
        platforms=", ".join(params.platforms),
        niche=params.niche or "any (general)",
        keywords=", ".join(params.keywords) or "none",
        categories=", ".join(params.categories),
        per_platform=per_platform,
        past_queries="\n".join(past) or "none",
    )
    try:
        plan = await structured_call(ctx.llm, QueryPlan, messages)
        queries = plan.queries
    except LLMQuotaExhausted:
        raise  # no LLM left: stop the run instead of wasting credits
    except Exception as e:  # never let one LLM hiccup kill the run
        log.warning("plan_queries LLM failed: %s", e)
        errors.append(f"plan_queries: LLM failed, used fallback queries ({e})")
        queries = []

    # Keep only requested platforms, drop repeats, cap the number per platform.
    seen = set(past)
    kept: list[SearchQuery] = []
    per_count: dict[str, int] = {}
    for q in queries:
        q.query = q.query.replace("site:", "").strip()  # the LLM was told not to, but just in case
        if q.platform not in params.platforms or not q.query or q.query in seen:
            continue
        if per_count.get(q.platform, 0) >= per_platform:
            continue
        per_count[q.platform] = per_count.get(q.platform, 0) + 1
        seen.add(q.query)
        kept.append(q)
    if not kept:
        kept = [q for q in fallback_queries(ctx.profile, params, round_no, per_platform) if q.query not in seen]

    emit("plan", f"{len(kept)} queries planned", queries=[f"[{q.platform}] {q.query}" for q in kept])
    return {
        "round": round_no,
        "queries": kept,
        "past_queries": past + [q.query for q in kept],
        "errors": errors,
    }
