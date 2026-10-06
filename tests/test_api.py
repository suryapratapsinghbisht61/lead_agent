"""API tests: fake Redis (fakeredis) + fake agent dependencies. No real Redis/LLM/Bright Data."""

import functools

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app import worker
from app.agent.fakes import FakeBrightData, FakeLLM
from app.agent.runner import run_agent
from app.api.main import app
from app.core import config
from app.db import repo


class FakeArqRedis(fakeredis.FakeAsyncRedis):
    """fakeredis + the one ARQ method the API uses."""

    enqueued: list = []

    async def enqueue_job(self, function, *args, _job_id=None, **kwargs):
        self.enqueued.append((function, args, _job_id))


@pytest.fixture
def server():
    return fakeredis.FakeServer()  # one in-memory "Redis server" shared by all fake clients


@pytest.fixture
def redis(server):
    FakeArqRedis.enqueued = []
    r = FakeArqRedis(server=server)  # the API's client (used inside TestClient's event loop)
    app.state.redis = r
    yield r
    app.state.redis = None


@pytest.fixture
def client(redis):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth():
    return {"X-API-Key": repo.create_api_key("test")}


def test_health_needs_no_key(client):
    body = client.get("/health").json()
    assert body["database"] is True and body["redis"] is True


def test_endpoints_require_a_valid_key(client):
    assert client.get("/leads").status_code == 401
    assert client.get("/leads", headers={"X-API-Key": "wrong"}).status_code == 401


async def test_full_flow_start_run_worker_results_update_export(client, redis, server, auth, monkeypatch):
    # 1) start a run -> queued in Redis, 202 returned immediately
    resp = client.post("/runs", json={"count": 2, "platforms": ["reddit", "x"]}, headers=auth)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    assert redis.enqueued == [("run_agent_job", (run_id, redis.enqueued[0][1][1]), run_id)]
    assert client.get(f"/runs/{run_id}", headers=auth).json()["run"]["status"] == "queued"

    # 2) simulate the ARQ worker picking it up (with fake LLM + Bright Data)
    monkeypatch.setattr(worker, "run_agent", functools.partial(run_agent, bd=FakeBrightData(), llm=FakeLLM()))
    worker_redis = FakeArqRedis(server=server)  # the worker's own client, same fake server
    out = await worker.run_agent_job({"redis": worker_redis}, run_id, redis.enqueued[0][1][1])
    assert out["qualified"] >= 2
    assert (await worker_redis.hgetall(f"run:{run_id}:progress"))[b"stage"] == b"done"

    # 3) results
    run = client.get(f"/runs/{run_id}", headers=auth).json()["run"]
    assert run["status"] == "completed" and run["qualified_count"] >= 2
    leads = client.get(f"/runs/{run_id}/leads", headers=auth).json()
    assert len(leads) >= 2 and leads[0]["message"]

    page = client.get("/leads", params={"platform": "x", "min_score": 6}, headers=auth).json()
    assert page["total"] >= 1 and all(lead["platform"] == "x" for lead in page["items"])

    # 4) update outreach status
    lead_id = leads[0]["id"]
    updated = client.patch(f"/leads/{lead_id}", json={"status": "sent", "notes": "DM sent"}, headers=auth).json()
    assert updated["status"] == "sent" and updated["notes"] == "DM sent"
    assert client.patch(f"/leads/{lead_id}", json={"status": "bogus"}, headers=auth).status_code == 422

    # 5) Excel exports
    for url in (f"/runs/{run_id}/export.xlsx", "/leads/export.xlsx"):
        r = client.get(url, headers=auth)
        assert r.status_code == 200 and r.content[:2] == b"PK"  # .xlsx files are zip archives

    # 6) live progress stream ends once the run is complete
    events = client.get(f"/runs/{run_id}/events", headers=auth)
    assert '"status": "completed"' in events.text


def test_unknown_ids_return_404(client, auth):
    assert client.get("/runs/nope", headers=auth).status_code == 404
    assert client.get("/leads/999", headers=auth).status_code == 404


def test_rate_limit_returns_429(client, auth, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    config.get_settings.cache_clear()
    codes = [client.get("/leads", headers=auth).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_run_limit_per_hour(client, auth, monkeypatch):
    monkeypatch.setenv("RUNS_PER_HOUR", "1")
    config.get_settings.cache_clear()
    assert client.post("/runs", json={"count": 1}, headers=auth).status_code == 202
    assert client.post("/runs", json={"count": 1}, headers=auth).status_code == 429


def test_invalid_run_params_rejected(client, auth):
    assert client.post("/runs", json={"count": 0}, headers=auth).status_code == 422
    assert client.post("/runs", json={"platforms": ["facebook"]}, headers=auth).status_code == 422
