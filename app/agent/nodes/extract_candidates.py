"""Node 3: the LLM reads search results and pulls out potential leads (structured output)."""

import asyncio

from langgraph.runtime import Runtime

from app.agent.prompts import profile_text
from app.agent.prompts.extract import EXTRACT_CANDIDATES
from app.agent.schemas import Candidate, CandidateList
from app.agent.state import AgentState, RunContext
from app.agent.utils import LLMQuotaExhausted, emit, infer_profile, normalize_url, structured_call

CHUNK_SIZE = 20  # results per LLM call (bigger = fewer calls against small free-tier quotas)


def format_results(results: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] platform: {r['platform']}\nTitle: {r.get('title', '')}\nURL: {r['url']}\nSnippet: {r.get('snippet', '')}"
        for i, r in enumerate(results, 1)
    )


async def extract_candidates(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    results = state.get("search_results", [])
    if not results:
        return {"candidates": []}
    emit("extract", f"Reading {len(results)} search results for potential leads")

    chunks = [results[i : i + CHUNK_SIZE] for i in range(0, len(results), CHUNK_SIZE)]

    async def run_chunk(chunk: list[dict]) -> tuple[list[Candidate], str | None]:
        messages = EXTRACT_CANDIDATES.format_messages(profile=profile_text(ctx.profile), results=format_results(chunk))
        try:
            out = await structured_call(ctx.llm, CandidateList, messages)
        except LLMQuotaExhausted:
            raise
        except Exception as e:
            return [], f"extract_candidates: LLM failed on a chunk ({e})"

        # Guard against hallucinations: only keep candidates whose source_url is a real result.
        by_url = {normalize_url(r["url"]): r for r in chunk}
        kept = []
        for c in out.candidates:
            result = by_url.get(normalize_url(c.source_url))
            if result is None:
                continue
            c.source_url = result["url"]
            c.platform = result["platform"]  # trust our own tagging over the model's
            kept.append(infer_profile(c))
        return kept, None

    outcomes = await asyncio.gather(*(run_chunk(ch) for ch in chunks))
    candidates = [c for found, _ in outcomes for c in found]
    errors = [err for _, err in outcomes if err]

    emit("extract", f"Found {len(candidates)} potential leads")
    return {"candidates": candidates, "errors": errors}
