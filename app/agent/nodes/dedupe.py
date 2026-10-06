"""Node 4: drop anyone already found in this run or in ANY previous run (via the database)."""

from langgraph.runtime import Runtime

from app.agent.schemas import Lead
from app.agent.state import AgentState, RunContext
from app.agent.utils import dedupe_keys, emit
from app.db import repo


def dedupe(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    candidates = state.get("candidates", [])
    seen_this_run = set(state.get("seen_keys", []))

    keys_per_candidate = [dedupe_keys(c) for c in candidates]
    in_database = repo.existing_keys([k for keys in keys_per_candidate for k in keys])

    new_leads: list[Lead] = []
    duplicates = 0
    for candidate, keys in zip(candidates, keys_per_candidate):
        if any(k in seen_this_run or k in in_database for k in keys):
            duplicates += 1
            continue
        seen_this_run.update(keys)
        new_leads.append(Lead(candidate=candidate, dedupe_keys=keys))

    emit("dedupe", f"{len(new_leads)} new leads, {duplicates} duplicates dropped")
    return {
        "pool": state.get("pool", []) + new_leads,
        "seen_keys": list(seen_this_run),
        "candidates": [],
    }
