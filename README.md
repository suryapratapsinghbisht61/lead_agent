# Lead Agent

An open-source AI agent that **finds people and businesses publicly struggling with repetitive manual work**, researches them, scores how well they fit your services, and **drafts a personalised outreach message** for each one.

Built with **LangGraph** (agent orchestration), **LangChain** (swappable LLMs: Gemini, Ollama, Claude, OpenAI), **Bright Data** (public web search + page fetching), **SQLite**, **FastAPI**, **Redis**, and **Streamlit**.

> It never sends anything. It drafts; you review and send manually.

![Dashboard screenshot](docs/screenshot.png)
<!-- TODO: add a screenshot or GIF of the dashboard at docs/screenshot.png -->

---

## What it does on each run

1. **Plans searches.** The LLM turns your request (count, niche, keywords, platforms) into targeted Google queries for Reddit, LinkedIn, X and the open web.
2. **Searches** them through Bright Data's SERP API (past 30 days by default).
3. **Extracts candidates** from the results with structured output: name, handle, company, the exact pain signal, and the source URL.
4. **Dedupes** against every lead from every previous run (profile URL, handle and company domain). The same person never comes back twice.
5. **Researches** each lead in parallel: the original post (Reddit JSON gives the author and date), plus the company homepage and any public email printed on it.
6. **Qualifies** each lead. It picks one category (startup / company / individual), lists pain points, and gives a fit score from 1 to 10 with a one-line reason. Low-fit leads are saved but hidden.
7. **Writes** "About them", "How I can help", and a channel-specific message under 100 words (LinkedIn note, X DM, Reddit DM, or email).
8. **Saves** to the database and exports Excel. If there are not enough qualified leads yet, it searches again (with a retry cap and a credit cap).

See the full graph in [docs/graph.md](docs/graph.md).

## Quick start (5 steps)

```bash
# 1. Clone and install (needs Python 3.11+ and uv: https://docs.astral.sh/uv/)
git clone https://github.com/suryapratapsinghbisht61/lead_agent.git && cd lead_agent
uv sync

# 2. Add your keys
cp .env.example .env        # then fill in GOOGLE_API_KEY and BRIGHTDATA_API_TOKEN

# 3. Describe YOUR business
#    edit config/services.yaml (your name, services, pain signals, target customers)

# 4. Check the connections
uv run python scripts/check_llm.py
uv run python scripts/check_brightdata.py

# 5. Find leads
uv run python scripts/run_cli.py --count 5 --niche "e-commerce"
```

No keys yet? Try everything on fake data first: `uv run python scripts/run_cli.py --demo --count 3`

## Three ways to use it

| Way | Command | Good for |
|---|---|---|
| **CLI** | `uv run python scripts/run_cli.py --count 10 --platforms reddit linkedin` | Quick runs, scripting |
| **Dashboard** | `uv run streamlit run dashboard/streamlit_app.py` → http://localhost:8501 | Browsing leads, copying messages, tracking status |
| **API** | `docker compose up --build` → http://localhost:8000/docs | Building your own frontend, automation |

CLI options: `--count`, `--niche`, `--keywords`, `--categories startup company individual`, `--platforms reddit linkedin x web`, `--days 30`, `--max-credits 200`, `--demo`, `--show-graph`, `--verbose`.

Manage leads from the terminal:

```bash
uv run python scripts/leads.py list --min-score 7
uv run python scripts/leads.py show 12
uv run python scripts/leads.py status 12 sent      # new | sent | replied | meeting | closed
uv run python scripts/leads.py runs
```

### API

```bash
docker compose up --build                                   # redis + api + worker + dashboard
docker compose exec api python scripts/api_keys.py create me   # copy the printed key
```

Open http://localhost:8000/docs, click **Authorize**, paste the key, and try the endpoints. Or use curl:

```bash
curl -X POST localhost:8000/runs -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"count": 5, "niche": "e-commerce", "platforms": ["reddit", "linkedin"]}'
curl localhost:8000/runs/<run_id> -H "X-API-Key: $KEY"           # status + live progress
curl localhost:8000/runs/<run_id>/leads -H "X-API-Key: $KEY"
curl -o leads.xlsx localhost:8000/leads/export.xlsx -H "X-API-Key: $KEY"
```

| Endpoint | What it does |
|---|---|
| `POST /runs` | Start a run (returns `run_id` immediately; a worker does the work) |
| `GET /runs`, `GET /runs/{id}` | Run history; status, progress, errors, credits used |
| `GET /runs/{id}/events` | Live progress as Server-Sent Events |
| `GET /runs/{id}/leads` | Leads from one run |
| `GET /leads` | All leads; filter by `category`, `platform`, `status`, `min_score`, `q`; paginated |
| `GET /leads/{id}`, `PATCH /leads/{id}` | One lead; update `status` / `notes` |
| `GET /runs/{id}/export.xlsx`, `GET /leads/export.xlsx` | Excel downloads |
| `GET /health` | Database + Redis status (no auth) |

Requests need an `X-API-Key` header. Keys are stored hashed. The API is rate-limited per key (`RATE_LIMIT_PER_MINUTE`, `RUNS_PER_HOUR`).

## Dashboard login

The dashboard always asks for an ID and password: every new visit, refresh or tab. Users come from the `DASHBOARD_USERS` setting (in `.env` locally, or your host's environment settings), **never from the code**:

```
DASHBOARD_USERS=myid:MyPassword,mom:AnotherPassword
```

Add a person = add `,id:password`. Remove = delete it. No commas inside passwords.

## Deploy on Render (free)

1. *(Recommended)* Create a free Postgres at [neon.tech](https://neon.tech) and copy its connection string. Without it, leads live in a temporary SQLite file that Render wipes on every restart or sleep.
2. On [render.com](https://render.com), sign in with GitHub → **New → Blueprint** → pick this repo. Render reads [`render.yaml`](render.yaml).
3. Fill in the secrets it asks for: `GOOGLE_API_KEY`, `BRIGHTDATA_API_TOKEN`, `DASHBOARD_USERS`, `DATABASE_URL` (Neon string, or empty).
4. **Apply**. After the build (~5–10 min) your link is at the top of the service page, e.g. `https://lead-agent-xxxx.onrender.com`.

To change users or keys later: service → **Environment** → edit → **Save** (Render restarts the app automatically). Free services sleep after ~15 min idle; the next visit takes ~30–60 s to wake.

## Customise it for your business

Everything about *you* lives in [`config/services.yaml`](config/services.yaml). No code changes are needed:

- `me`: your name, one-line pitch, portfolio link (used to sign messages)
- `services`: what you sell, in plain words
- `pain_signals` / `hiring_signals`: phrases that show someone needs you
- `subreddits`: where your customers hang out
- `target`: preferred categories, boosted niches, who to avoid

Prompt wording lives in [`app/agent/prompts/`](app/agent/prompts/) if you want to change tone or scoring rules.

## Switching models

Set two lines in `.env`:

| Provider | `.env` | Notes |
|---|---|---|
| Gemini (default) | `LLM_PROVIDER=google_genai`, `LLM_MODEL=gemini-3.5-flash` | Free key at https://aistudio.google.com/apikey. `scripts/check_llm.py --list-models` shows what your key can use |
| Ollama (local) | `LLM_PROVIDER=ollama`, `LLM_MODEL=qwen2.5:3b` | `ollama pull qwen2.5:3b`. Small models are weaker at structured output; 7B+ is better if you have the RAM |
| Claude / OpenAI | `LLM_PROVIDER=anthropic` or `openai` + model name | `uv add langchain-anthropic` / `langchain-openai` and set the provider's API key |

## Cost notes (free tiers)

- **Bright Data** has a free tier with monthly credits. Each search or page fetch is one paid request. Cached repeats (72 h) are free. A 10-lead run typically makes about **40–80 requests**: roughly 12 searches plus 1–2 fetches per researched lead. `MAX_CREDITS_PER_RUN` (default 200) is a hard stop. Check your Bright Data dashboard for the exact cost per request on your plan.
- **Gemini free tier** has per-minute and per-day request limits. A 10-lead run makes about **30–50 LLM calls**, which the built-in rate limiter (`LLM_REQUESTS_PER_MINUTE=10`) spreads over a few minutes.
- **Ollama** is free and runs locally.

## Development

```bash
uv run pytest            # 34 tests, fully offline (fake LLM, fake Bright Data, fake Redis)
uv run python scripts/run_cli.py --show-graph   # regenerate docs/graph.md
```

- What each library does: [docs/LIBRARIES.md](docs/LIBRARIES.md)
- What each folder and file does: [docs/FOLDERS.md](docs/FOLDERS.md)

## Roadmap

- [ ] Next.js / React web frontend on top of the API (the `/runs/{id}/events` stream is ready for live progress)
- [ ] Optional Bright Data LinkedIn/X profile scrapers for richer research
- [ ] Postgres option in Docker Compose

## Disclaimer

This tool collects **publicly available** information only. It does not log in to any account or bypass login walls, and it **never sends messages automatically**.

**You are responsible** for how you use it, including compliance with each platform's Terms of Service and with privacy and anti-spam laws such as the **GDPR** (EU/UK), **India's DPDP Act 2023**, and **CAN-SPAM** (US). Only contact people where you have a legitimate reason to, honour opt-out requests, and delete data you no longer need.

## License

[MIT](LICENSE)
