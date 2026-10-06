# Libraries: what each one does and where we use it

All versions are pinned in `pyproject.toml`, and `uv.lock` records the exact version of every sub-dependency too.
Install everything with `uv sync`.

---

## The AI part

### LangGraph `1.2.12`: runs the agent
**What it is:** A library for building agents as a **graph**. Each step is a *node* (a Python function), *edges* say which step comes next, and a shared *state* (a dict) flows through all of them.

**Why we need it:** Our agent is not a straight line. It **loops** (search again if there aren't enough leads), **branches** (low-fit leads skip message writing), and **fans out** (researches many leads at the same time). LangGraph gives us all three with very little code.

**Concepts we use, and where:**
| Concept | What it means | Where |
|---|---|---|
| `StateGraph` | The graph builder | `app/agent/graph.py` |
| State `TypedDict` + `Annotated[list, operator.add]` | Shared data. "add" means parallel workers *append* results instead of overwriting each other | `app/agent/state.py` |
| `add_edge` / `add_conditional_edges` | Fixed next step / decide the next step with a function | `graph.py`, `nodes/pick_batch.py`, `nodes/qualify.py` |
| `Send` | "Run this node once per item, in parallel" (map-reduce) | `nodes/pick_batch.py` → `route_after_pick` |
| Subgraph | A compiled graph used as a node (our per-lead pipeline) | `graph.py` → `build_lead_graph()` |
| `context_schema` + `Runtime` | Pass non-data things (Bright Data client, LLM, profile) to every node | `state.py` → `RunContext`; each node's `runtime.context` |
| `get_stream_writer()` + `astream(stream_mode="custom")` | Nodes emit progress events that the CLI, dashboard and worker display live | `app/agent/utils.py` → `emit()`; `app/agent/runner.py` |
| `max_concurrency` | Limits how many leads are researched at once | `runner.py` |
| `draw_mermaid()` | Draws the graph | `graph.py` → `mermaid()` |

### LangChain `1.4.3` (+ `langchain-core` `1.6.6`): talks to the LLM
**What it is:** A standard interface for chat models, prompts and structured output, the same code for every provider.

**Where:**
- `init_chat_model(model, model_provider=...)` in `app/services/llm.py` lets you **swap Gemini ↔ Ollama ↔ Claude ↔ OpenAI by editing `.env`**.
- `InMemoryRateLimiter` in `llm.py` keeps Gemini's free tier under its requests-per-minute limit.
- `ChatPromptTemplate` in `app/agent/prompts/*.py` defines prompt templates with `{placeholders}`, kept out of node code.
- `.with_structured_output(PydanticModel)` in `app/agent/utils.py` → `structured_call()`. The model must return a filled-in Pydantic object, so we never parse free text.

**LangChain vs LangGraph in one line:** LangChain handles *one conversation with the model*; LangGraph decides *which step runs when*.

### langchain-google-genai `4.4.0`
The Gemini connector LangChain uses when `LLM_PROVIDER=google_genai`. It installs Google's `google-genai` SDK too, which `scripts/check_llm.py --list-models` uses.

### langchain-ollama `1.1.0`
The Ollama connector, used when `LLM_PROVIDER=ollama`, for free local models.

### Pydantic (comes with FastAPI/LangChain)
Data classes with validation. **Every** LLM output schema (`QueryPlan`, `CandidateList`, `Qualification`, `Outreach`) and every API request/response is a Pydantic model. See `app/agent/schemas.py` and `app/api/schemas.py`.

---

## Getting web data

### brightdata-sdk `2.5.2`: search + fetch public pages
**What it is:** Bright Data's official Python client.
**Where:** `app/services/brightdata.py`
- `client.search.google(query, time_range="m")` (SERP API) returns Google results as JSON, limited to the past month.
- `client.scrape_url(url)` (Web Unlocker) fetches any public page, handling blocks and CAPTCHAs.
- `auto_create_zones=True` means the SDK creates the needed zones in your account automatically.

Our wrapper adds caching, a per-run credit budget (`CreditLimitReached`), and usage counting.

### beautifulsoup4 `4.15.0`
Turns HTML into plain readable text before we give it to the LLM (fewer tokens, less noise). Used in `brightdata.py` → `html_to_text()`.

### diskcache `5.6.3`
A key/value cache stored on disk (a SQLite file in `.cache/`) with expiry times. Every Bright Data response is cached for `CACHE_TTL_HOURS`, so re-runs don't spend credits again. Used in `app/services/cache.py`.

---

## Storing data

### SQLModel `0.0.47` (built on SQLAlchemy + Pydantic)
**What it is:** Define a class once and it is both a database table and a Pydantic model.
**Where:**
- `app/db/models.py` defines the tables `runs`, `leads`, `lead_keys` (dedup) and `api_keys`.
- `app/db/session.py` handles the connection (`DATABASE_URL`, SQLite by default, Postgres later).
- `app/db/repo.py` holds all queries: create and update runs, save leads, dedup lookups, filters, API keys.

The FastAPI endpoints return these same models directly.

### psycopg `3.3.3`
The PostgreSQL driver. Only used when `DATABASE_URL` points to Postgres (e.g. a free Neon database for hosting). `app/db/session.py` → `normalize_db_url()` turns `postgresql://...` into the form SQLAlchemy needs.

### certifi
A bundle of trusted SSL certificates. `brightdata.py` passes it to the Bright Data SDK so HTTPS works on macOS Pythons that can't see the system certificates.

### openpyxl `3.1.5`
Writes `.xlsx` Excel files with bold headers, wrapped text and frozen header rows. Used in `app/services/export.py` (by the CLI, dashboard and API exports).

---

## Configuration and reliability

### pydantic-settings `2.15.0`
Reads `.env` and environment variables into one typed `Settings` object. Used in `app/core/config.py`. Everything else calls `get_settings()`.

### PyYAML `6.0.3`
Reads `config/services.yaml` (your business profile) in `config.py`, and turns it back into text for prompts in `prompts/__init__.py`.

### tenacity `9.1.4`
Retry with exponential backoff. In `app/agent/utils.py` → `structured_call()`, if the model returns malformed structured output (small local models sometimes do), we retry up to 3 times. Network retries are already handled by the LLM client (`max_retries=3`) and the Bright Data SDK, so we don't double-retry.

### httpx `0.28.1`
An HTTP client. FastAPI's `TestClient` uses it in our API tests, and the SDKs use it internally.

---

## The web app stage

### FastAPI `0.142.2`: the REST API
**What it is:** A modern async web framework. You write Python functions with type hints, and it validates requests, serialises responses, and generates interactive docs at `/docs`.
**Where:** `app/api/`
- `main.py`: the app, the CORS setup, startup/shutdown (`lifespan`), and `/health`.
- `routes/runs.py`, `routes/leads.py`: the endpoints.
- `deps.py`: *dependencies*, the functions FastAPI runs before an endpoint (API-key check, rate limit).

### Uvicorn `0.54.0`
The server that actually runs the FastAPI app: `uvicorn app.api.main:app`.

### Redis client `5.3.1` (`redis[hiredis]`)
**What Redis is:** A very fast in-memory database for short-lived data. We use it for:
- **Job queue** (through ARQ, below)
- **Live progress** per run: `app/services/jobs.py` → `set_progress()` / `get_progress()`
- **Rate limiting**: `app/api/deps.py` → `_hit()` (a counter per key per minute or hour)

Pinned to 5.x because ARQ requires `redis<6`.

### ARQ `0.28.0`: background jobs
**What it is:** A small async job queue on Redis. The API puts a job in the queue (`enqueue_job`), and a separate **worker** process picks it up and runs it.
**Why:** A run takes minutes. `POST /runs` returns a `run_id` instantly, and the run keeps going even if the API restarts.
**Where:** `app/worker.py` (`WorkerSettings`, `run_agent_job`); enqueued in `routes/runs.py`.

### Streamlit `1.65.0`: the dashboard
**What it is:** Build web UIs in pure Python. The script re-runs top to bottom on every click, and `st.session_state` keeps values between re-runs.
**Where:** `dashboard/streamlit_app.py`. It provides the run form, live progress, leads table with filters, lead detail with a copy button, status tracking and Excel download. It calls the agent directly; no API needed.

### pandas (comes with Streamlit)
Turns lead lists into tables for `st.dataframe` in the dashboard.

---

## Testing (dev only)

| Library | Use |
|---|---|
| **pytest** | Test runner (`uv run pytest`) |
| **pytest-asyncio** | Lets tests be `async def` (the agent is async) |
| **fakeredis** | An in-memory fake Redis for API tests |
| **Streamlit `AppTest`** (built in) | Clicks through the dashboard headlessly in `tests/test_dashboard.py` |
| **Our own fakes** | `app/agent/fakes.py`: `FakeLLM` and `FakeBrightData` return realistic data with no keys and no cost (also powers `--demo` and `DEMO_MODE`) |

## Tools (not Python libraries)

| Tool | Use |
|---|---|
| **uv** | Installs Python and packages, manages `.venv`, runs commands (`uv run ...`) |
| **Docker / Docker Compose** | Runs Redis + API + worker + dashboard together (`docker compose up --build`) |
| **Ollama** | Runs local LLMs on your machine |
