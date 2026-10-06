"""Node 5 (the loop controller): decide what happens next.

  * enough qualified leads?            -> save_results
  * new leads waiting in the pool?     -> research a batch of them IN PARALLEL (Send)
  * pool empty, rounds/credits left?   -> plan_queries again (new search round)
  * otherwise                          -> save_results
"""

from langgraph.runtime import Runtime
from langgraph.types import Send

from app.agent.state import AgentState, RunContext
from app.agent.utils import emit


def pick_batch(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    params = state["params"]
    qualified = sum(lead.is_qualified(ctx.min_fit_score) for lead in state.get("processed", []))
    needed = params.count - qualified
    pool = state.get("pool", [])

    if needed <= 0:
        return {"batch": [], "stop_reason": f"target reached ({qualified} qualified leads)"}

    if pool:
        # About half of researched leads qualify, so research ~2x what we still need.
        size = min(len(pool), needed * ctx.batch_multiplier)
        emit("research", f"Researching {size} leads ({qualified}/{params.count} qualified so far)",
             qualified=qualified, target=params.count)
        return {"batch": pool[:size], "pool": pool[size:]}

    if ctx.bd.credits_used >= ctx.bd.max_credits:
        return {"batch": [], "stop_reason": f"credit budget used up ({ctx.bd.credits_used} credits)"}
    if state.get("round", 0) >= ctx.max_rounds:
        return {"batch": [], "stop_reason": f"stopped after {ctx.max_rounds} search rounds"}

    emit("plan", f"Need {needed} more qualified leads, starting another search round")
    return {"batch": [], "stop_reason": ""}


def route_after_pick(state: AgentState):
    """Conditional edge. Returning a list of Send(...) = run that node once per item, in parallel."""
    if state.get("batch"):
        return [Send("process_lead", {"lead": lead, "params": state["params"]}) for lead in state["batch"]]
    if state.get("stop_reason"):
        return "save_results"
    return "plan_queries"
