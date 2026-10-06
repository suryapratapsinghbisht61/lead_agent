# Folder guide: what's in each folder and what it does

```
lead-agent/
├── app/                    all the real code (an installable Python package)
│   ├── core/               settings + logging
│   ├── services/           connections to the outside world (LLM, Bright Data, cache, export, Redis progress)
│   ├── agent/              the LangGraph agent
│   │   ├── nodes/          one file per step of the agent
│   │   └── prompts/        what we say to the LLM, one file per step
│   ├── db/                 database tables + all queries
│   ├── api/                FastAPI server
│   │   └── routes/         the endpoints
│   └── worker.py           background worker for API runs
├── config/                 YOUR business profile (services.yaml)
├── dashboard/              Streamlit dashboard
├── scripts/                commands you run in the terminal
├── tests/                  automated tests (offline)
├── docs/                   these docs + the graph diagram
├── data/                   the SQLite database (git-ignored)
├── exports/                Excel files (git-ignored)
├── logs/                   log files (git-ignored)
├── .cache/                 cached Bright Data responses (git-ignored)
└── .venv/                  installed packages (git-ignored)
```

---

## How a run flows through the folders

```
scripts/run_cli.py  or  dashboard/  or  api/ → worker.py
                │
                ▼
      app/agent/runner.py  run_agent()          creates the run row, opens Bright Data, streams the graph
                │
                ▼
      app/agent/graph.py   the LangGraph graph
                │  calls, in order:
                ▼
      app/agent/nodes/*.py ──uses──► app/agent/prompts/*.py   (what to ask the LLM)
                │          ──uses──► app/services/llm.py      (Gemini / Ollama)
                │          ──uses──► app/services/brightdata.py (search + fetch, cached)
                │          ──uses──► app/db/repo.py           (dedup + save)
                ▼
      data/leads.db  +  exports/leads_<run_id>.xlsx
```

---

## `app/core/`: settings and logging
| File | What it does |
|---|---|
| `config.py` | Reads `.env` into one typed `Settings` object (`get_settings()`), and loads `config/services.yaml` (`load_profile()`). Every other file gets settings from here. |
| `auth.py` | Dashboard login: reads `id:password` pairs from `DASHBOARD_USERS` and checks them safely. |
| `logging.py` | One logging setup: readable console lines plus `logs/agent.log`. Quiets noisy libraries. |

## `app/services/`: talking to the outside world
The agent never deals with APIs directly. It calls these small wrappers.

| File | What it does |
|---|---|
| `llm.py` | `get_llm()` returns the chat model chosen in `.env` (Gemini/Ollama/...), with a rate limiter and retries. |
| `brightdata.py` | `BrightData` class: `search()` (Google results), `fetch_raw()` / `fetch_page()` (any public page). Adds caching, a per-run credit budget, and usage counting. `html_to_text()` cleans HTML. |
| `cache.py` | Disk cache (`.cache/`) with expiry, so repeat searches and pages cost no credits. |
| `export.py` | Turns lead rows into Excel (`leads_to_xlsx`) or CSV. |
| `jobs.py` | Writes and reads **live run progress** in Redis (used by the worker and API). |

## `app/agent/`: the LangGraph agent
| File | What it does |
|---|---|
| `schemas.py` | All data shapes. **LLM outputs**: `QueryPlan`, `CandidateList`, `Qualification`, `Outreach`. **Internal**: `RunParams` (what you asked for), `Lead` (one lead moving through the steps). |
| `state.py` | `AgentState` (data flowing through the main graph), `LeadState` (data inside the per-lead subgraph), and `RunContext` (tools every node can use: Bright Data, LLM, profile, settings). |
| `graph.py` | **Wires the nodes together.** Read this file first to understand the agent. `mermaid()` draws it. |
| `runner.py` | `run_agent()` is the one entry point used by the CLI, dashboard and worker. It creates the run in the DB, runs the graph, forwards progress, and records success or failure. |
| `utils.py` | Helpers: `emit()` (progress events), `structured_call()` (LLM call with retries), URL normalising, dedupe keys, public-email finder, date filter. |
| `fakes.py` | `FakeLLM` and `FakeBrightData`, used by tests, `--demo` and `DEMO_MODE`. |

### `app/agent/nodes/`: one file per step
| File | Step | LLM? | Bright Data? |
|---|---|---|---|
| `plan_queries.py` | 1. Turn your request into search queries per platform (falls back to `services.yaml` signals if the LLM fails) | yes | no |
| `search_sources.py` | 2. Run all queries in parallel through Google SERP; drop repeats and off-platform results | no | yes |
| `extract_candidates.py` | 3. Read results and pull out leads; reject any source URL the LLM invented | yes | no |
| `dedupe.py` | 4. Drop anyone seen earlier in this run or in **any previous run** (database) | no | no |
| `pick_batch.py` | 5. **The loop controller**: enough leads → save; leads waiting → research a batch in parallel (`Send`); nothing left → search again; out of rounds/credits → save | no | no |
| `research_lead.py` | 6a. *(per lead)* Fetch the post (Reddit JSON → author + date) and the company homepage (+ public email) | no | yes |
| `qualify.py` | 6b. *(per lead)* Category, pain points, fit score 1–10 + reason. Low fit → skip writing | yes | no |
| `write_outreach.py` | 6c. *(per lead)* "About them", "How I can help", and a channel-specific message. Also `finish_lead`, which hands the lead back to the main graph | yes | no |
| `save_results.py` | 7. Save to the database and write the Excel file | no | no |

### `app/agent/prompts/`: what we tell the LLM
| File | Used by |
|---|---|
| `__init__.py` | `profile_text()` formats `services.yaml` for prompts |
| `plan_queries.py` | `plan_queries` node |
| `extract.py` | `extract_candidates` node |
| `qualify.py` | `qualify` node (scoring rules live here) |
| `outreach.py` | `write_outreach` node (message rules + per-channel format rules) |

Change wording or scoring here; no node code needs to change.

## `app/db/`: the database
| File | What it does |
|---|---|
| `models.py` | Tables: **`runs`** (history, status, credits), **`leads`** (everything about a lead + your outreach status/notes), **`lead_keys`** (every identity of a lead, used for dedup), **`api_keys`** (hashed). |
| `session.py` | Connects using `DATABASE_URL`; `init_db()` creates the tables. |
| `repo.py` | **Every** query in one place: create/update runs, `existing_keys()` for dedup, `save_leads()`, `list_leads()` with filters and pagination, `update_lead()`, and API key create/find/revoke. |

## `app/api/`: the FastAPI server (web-app stage)
| File | What it does |
|---|---|
| `main.py` | Creates the app, CORS, startup (DB + Redis/ARQ pool), `/health`. |
| `deps.py` | `require_api_key` (checks the `X-API-Key` header against hashed keys), `rate_limited` / `run_rate_limited` (Redis counters). |
| `schemas.py` | Response shapes: `RunCreated`, `RunOut`, `LeadPage`, `LeadUpdate`, `Health`. |
| `routes/runs.py` | `POST /runs` (queue a run), `GET /runs`, `GET /runs/{id}`, `/events` (live SSE), `/leads`, `/export.xlsx` |
| `routes/leads.py` | `GET /leads` (filters + pagination), `GET/PATCH /leads/{id}`, `/leads/export.xlsx` |

## `app/worker.py`: background worker
An ARQ worker (`uv run arq app.worker.WorkerSettings`). It picks up runs queued by the API, calls `run_agent()`, and writes live progress to Redis.

## `config/`
| File | What it does |
|---|---|
| `services.yaml` | **The only file someone who forks the repo must edit.** Your name/signature, services, pain signals, hiring signals, subreddits, preferred categories, boosted niches, who to avoid. |

## `dashboard/`
| File | What it does |
|---|---|
| `streamlit_app.py` | **Login screen first** (users from `DASHBOARD_USERS`), then three pages: **Find leads** (form → live progress → results), **Leads** (filters, table, detail with copy-message button, status/notes, Excel download), **Runs** (history + per-run download). It has a demo-mode toggle. (Not called `app.py` because that would clash with the `app` package.) |

## `scripts/`: terminal commands
| File | What it does |
|---|---|
| `run_cli.py` | Run the agent: `--count --niche --keywords --categories --platforms --days --max-credits --demo --show-graph --verbose` |
| `leads.py` | `list`, `show`, `status`, `note`, `runs`, `export` |
| `api_keys.py` | `create`, `list`, `revoke` API keys |
| `check_llm.py` | Hello-world + structured-output test for your LLM; `--list-models` |
| `check_brightdata.py` | One search + one page fetch; run twice to see caching |

## `tests/`: automated tests (`uv run pytest`, fully offline)
| File | What it tests |
|---|---|
| `conftest.py` | Gives every test its own empty database, cache and export folder |
| `test_foundations.py` | Settings, profile loading, cache, HTML cleaning |
| `test_utils.py` | URL normalising, dedupe keys, profile inference, email finder, date filter |
| `test_agent.py` | Full agent runs: qualified leads + export, **no duplicates across runs**, low-fit hidden, credit cap, LLM failure handling, category filter |
| `test_api.py` | Auth, start run → worker → results, filters, PATCH, Excel, SSE, 404s, rate limits |
| `test_auth.py` | Login parsing/checking, Postgres URL handling |
| `test_dashboard.py` | Login required, wrong password rejected, then clicks through the dashboard headlessly in demo mode |

## `docs/`
`LIBRARIES.md` (every library and where it's used), `FOLDERS.md` (this file), `graph.md` (agent diagram, regenerate with `run_cli.py --show-graph`).

## Root files
| File | What it does |
|---|---|
| `pyproject.toml` / `uv.lock` | Dependencies (pinned) and the exact versions of everything |
| `.env.example` → `.env` | Settings template → your real keys (`.env` is never committed) |
| `.gitignore` / `.dockerignore` | What git / Docker should ignore (secrets, data, caches) |
| `Dockerfile` | One image for API, worker and dashboard |
| `render.yaml` | Render "Blueprint": how Render builds and runs the dashboard, and which secrets it asks for |
| `deploy/start-dashboard.sh` | Starts the dashboard on the port the host gives (`$PORT`) |
| `docker-compose.yml` | Starts Redis + API + worker + dashboard together |
| `README.md` | Project overview, setup in 5 steps, usage, costs, disclaimer |
| `LICENSE` | MIT |
| `.python-version` | Tells uv which Python to use |
