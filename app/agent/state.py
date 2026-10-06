"""Graph state + run context.

STATE = the data that flows between nodes. Each node returns a dict with only
the keys it changed, and LangGraph merges that into the state.
Keys marked Annotated[..., operator.add] are *appended to* instead of replaced,
which is what lets many parallel lead-workers each add their result safely.

CONTEXT = things every node needs but that are not "data": the Bright Data
client, the LLM, your profile, settings. Nodes read it via runtime.context.
"""

import operator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from app.agent.schemas import Candidate, Lead, RunParams, SearchQuery


class AgentState(TypedDict, total=False):
    params: RunParams
    round: int  # how many search rounds have started
    queries: list[SearchQuery]  # queries for the current round
    past_queries: list[str]  # every query used so far (so the LLM doesn't repeat itself)
    search_results: list[dict]  # raw results for the current round
    seen_urls: list[str]  # result URLs already looked at this run
    candidates: list[Candidate]  # extracted this round, before dedup
    seen_keys: list[str]  # dedupe keys already taken this run
    pool: list[Lead]  # new leads waiting to be researched
    batch: list[Lead]  # leads being researched right now
    processed: Annotated[list[Lead], operator.add]  # finished leads (any score)
    errors: Annotated[list[str], operator.add]  # non-fatal problems
    stop_reason: str  # why the run ended
    summary: dict  # filled by save_results


# ---- per-lead subgraph (research -> qualify -> write_outreach)
class LeadInput(TypedDict):
    lead: Lead
    params: RunParams


class LeadOutput(TypedDict):
    processed: Annotated[list[Lead], operator.add]
    errors: Annotated[list[str], operator.add]


class LeadState(LeadInput, LeadOutput):
    pass


@dataclass
class RunContext:
    run_id: str
    bd: Any  # app.services.brightdata.BrightData (or a fake in tests)
    llm: Any  # a LangChain chat model, a list [main, *fallbacks], or a fake in tests
    profile: dict  # config/services.yaml
    min_fit_score: int = 6
    max_rounds: int = 4  # search rounds before giving up
    batch_multiplier: int = 2  # research ~2x the leads still needed (about half qualify)
