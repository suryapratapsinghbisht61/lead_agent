"""Node 2: run every planned query through Bright Data's Google SERP API, in parallel."""

import asyncio

from langgraph.runtime import Runtime

from app.agent.schemas import SearchQuery
from app.agent.state import AgentState, RunContext
from app.agent.utils import SITE_FILTERS, emit, normalize_url, time_range_for
from app.services.brightdata import CreditLimitReached

PLATFORM_DOMAINS = {
    "reddit": ("reddit.com",),
    "linkedin": ("linkedin.com",),
    "x": ("x.com", "twitter.com"),
}


def matches_platform(url: str, platform: str) -> bool:
    """Is this result really from the platform we searched? ("web" = anything else)."""
    norm = normalize_url(url) or ""
    if platform == "web":
        return not any(norm.startswith(d) for ds in PLATFORM_DOMAINS.values() for d in ds)
    return any(norm.startswith(d) for d in PLATFORM_DOMAINS[platform])


async def search_sources(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    params = state["params"]
    queries: list[SearchQuery] = state.get("queries", [])
    time_range = time_range_for(params.days)
    emit("search", f"Searching Google with {len(queries)} queries")

    async def run_one(q: SearchQuery) -> tuple[list[dict], str | None]:
        full_query = f"{q.query} {SITE_FILTERS[q.platform]}"
        try:
            results = await ctx.bd.search(full_query, num_results=10, time_range=time_range)
        except CreditLimitReached as e:
            return [], f"search skipped, budget reached: {e}"
        except Exception as e:
            return [], f"search failed for {full_query!r}: {e}"
        return [{**r, "platform": q.platform, "query": q.query} for r in results], None

    outcomes = await asyncio.gather(*(run_one(q) for q in queries))

    seen = set(state.get("seen_urls", []))
    fresh: list[dict] = []
    errors: list[str] = []
    for results, error in outcomes:
        if error:
            errors.append(error)
        for r in results:
            key = normalize_url(r["url"])
            if not key or key in seen or not matches_platform(r["url"], r["platform"]):
                continue
            seen.add(key)
            fresh.append(r)

    emit("search", f"{len(fresh)} new search results")
    return {"search_results": fresh, "seen_urls": list(seen), "errors": errors}
