"""run_agent(): the ONE function everybody calls to run the agent (CLI, dashboard, API worker).

It creates the run row, opens Bright Data, streams the graph, reports progress,
and records the outcome (completed or failed) in the database.
"""

import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable

from app.agent.graph import graph
from app.agent.schemas import RunParams
from app.agent.state import RunContext
from app.core.config import get_settings, load_profile
from app.db import repo
from app.db.models import utcnow
from app.db.session import init_db

log = logging.getLogger(__name__)

# A plain function or an async function; both work.
ProgressCallback = Callable[[dict], None | Awaitable[None]]


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


async def run_agent(
    params: RunParams,
    run_id: str | None = None,
    on_progress: ProgressCallback | None = None,
    bd=None,  # inject a fake in tests; default = real Bright Data
    llm=None,  # inject a fake in tests; default = get_llm()
) -> dict:
    settings = get_settings()
    init_db()
    run_id = run_id or new_run_id()
    if repo.get_run(run_id) is None:
        repo.create_run(run_id, params.model_dump())
    repo.update_run(run_id, status="running", started_at=utcnow(), progress="Starting")

    async def report(event: dict) -> None:
        repo.update_run(run_id, progress=event.get("message", ""))
        if on_progress:
            result = on_progress(event)
            if inspect.isawaitable(result):
                await result

    final: dict = {}  # latest full graph state (kept so we can save partial results on failure)
    try:
        if settings.demo_mode and bd is None and llm is None:
            from app.agent.fakes import FakeBrightData, FakeLLM

            bd, llm = FakeBrightData(), FakeLLM()
        if bd is None:
            from app.services.brightdata import BrightData

            bd = BrightData(max_credits=params.max_credits)
        if llm is None:
            from app.services.llm import get_llms

            llm = get_llms()  # [main model, *fallbacks]

        async with bd:
            context = RunContext(
                run_id=run_id,
                bd=bd,
                llm=llm,
                profile=load_profile(),
                min_fit_score=settings.min_fit_score,
                max_rounds=settings.max_search_rounds,
            )
            # stream_mode "custom" = our emit() progress events; "values" = full state after each step.
            # subgraphs=True also delivers events from inside the per-lead subgraph.
            async for namespace, mode, chunk in graph.astream(
                {"params": params, "processed": [], "errors": []},
                context=context,
                stream_mode=["custom", "values"],
                subgraphs=True,
                config={"max_concurrency": settings.max_concurrency, "recursion_limit": 300},
            ):
                if mode == "custom":
                    await report(chunk)
                elif mode == "values" and not namespace:  # top-level state only
                    final = chunk
            usage = bd.usage()

        summary = final.get("summary", {})
        errors = final.get("errors", [])
        repo.update_run(
            run_id,
            status="completed",
            finished_at=utcnow(),
            progress="Done",
            qualified_count=summary.get("qualified", 0),
            processed_count=summary.get("processed", 0),
            credits_used=usage["credits_used"],
            cost_usd=usage["cost_usd"],
            errors=errors[:100],
            stop_reason=summary.get("stop_reason"),
            export_path=summary.get("export_path"),
        )
        return {"run_id": run_id, **summary, "usage": usage, "errors": errors}

    except Exception as e:
        log.exception("Run %s failed", run_id)
        # Keep whatever leads were already finished before the failure.
        saved = repo.save_leads(run_id, final.get("processed", []), settings.min_fit_score)
        qualified = sum(1 for r in saved if not r.low_fit)
        repo.update_run(run_id, status="failed", finished_at=utcnow(), progress=f"Failed: {e}",
                        errors=[str(e)], qualified_count=qualified, processed_count=len(final.get("processed", [])))
        raise
    except BaseException:
        # Cancelled, Ctrl+C, or Streamlit stopping the script (page closed/refreshed): not an
        # Exception, so without this the run would stay "running" forever.
        log.warning("Run %s interrupted", run_id)
        repo.update_run(run_id, status="failed", finished_at=utcnow(),
                        progress="Interrupted: the run was stopped before it finished",
                        errors=["interrupted"], processed_count=len(final.get("processed", [])))
        raise
