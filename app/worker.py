"""ARQ background worker: runs agent jobs queued by the API.

    uv run arq app.worker.WorkerSettings

Why a separate worker process? A run takes minutes. The API answers POST /runs
immediately with a run_id, and this process does the slow work. If the API
restarts, running jobs are not lost.
"""

from arq.connections import RedisSettings

from app.agent.runner import run_agent
from app.agent.schemas import RunParams
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import init_db
from app.services.jobs import set_progress


async def run_agent_job(ctx: dict, run_id: str, params: dict) -> dict:
    redis = ctx["redis"]  # ARQ hands every job a Redis connection

    async def on_progress(event: dict) -> None:
        await set_progress(redis, run_id, event)

    try:
        result = await run_agent(RunParams(**params), run_id=run_id, on_progress=on_progress)
    except Exception as e:
        await set_progress(redis, run_id, {"stage": "failed", "message": f"Failed: {e}"})
        raise
    await set_progress(redis, run_id, {"stage": "done", "message": "Done"})
    return {k: result.get(k) for k in ("run_id", "qualified", "low_fit_saved", "stop_reason", "export_path")}


async def startup(ctx: dict) -> None:
    setup_logging(get_settings().log_level)
    init_db()


class WorkerSettings:
    functions = [run_agent_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 60 * 60  # a run may take up to an hour
    max_jobs = 2  # runs at the same time (free LLM tiers are slow; keep it low)
    keep_result = 24 * 3600
