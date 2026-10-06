"""FastAPI app.

    uv run uvicorn app.api.main:app --reload       # then open http://localhost:8000/docs

Needs Redis running (docker run -d -p 6379:6379 redis:7-alpine) and a worker
(uv run arq app.worker.WorkerSettings) to actually execute runs.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import leads, runs
from app.api.schemas import Health
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before yield) and once at shutdown (after yield)."""
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()
    created_here = False
    if getattr(app.state, "redis", None) is None:  # tests inject a fake Redis instead
        # An ARQ pool is a normal async Redis client that can also enqueue jobs.
        app.state.redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        created_here = True
    yield
    if created_here:
        await app.state.redis.aclose()


app = FastAPI(
    title="Lead Agent API",
    description="Find, research and draft outreach for qualified leads. Authorize with your X-API-Key.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(runs.router)
app.include_router(leads.router)


@app.get("/health", response_model=Health, tags=["health"])
async def health() -> Health:
    """No auth. Reports whether the database and Redis are reachable."""
    s = get_settings()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(await app.state.redis.ping())
    except Exception:
        redis_ok = False
    return Health(status="ok" if db_ok and redis_ok else "degraded", database=db_ok, redis=redis_ok,
                  llm=f"{s.llm_provider}/{s.llm_model}", time=datetime.now(timezone.utc))
