"""End-to-end agent tests with fake LLM + fake Bright Data."""

from app.agent.runner import run_agent
from app.agent.schemas import RunParams
from app.db import repo
from app.db.models import LeadKey
from app.db.session import get_session
from sqlmodel import select

from app.agent.fakes import FakeBrightData, FakeLLM


async def test_full_run_finds_qualified_leads_and_exports():
    events = []
    result = await run_agent(RunParams(count=3, platforms=["reddit", "web"]), on_progress=events.append,
                             bd=FakeBrightData(), llm=FakeLLM())

    assert result["qualified"] >= 3
    assert result["export_path"] and result["export_path"].endswith(".xlsx")
    run = repo.get_run(result["run_id"])
    assert run.status == "completed" and run.qualified_count >= 3
    leads, total = repo.list_leads(run_id=result["run_id"])
    assert total >= 3
    assert all(lead.message and lead.about_them and lead.how_i_can_help for lead in leads)
    # Reddit leads got their author from the post JSON; web leads got the public email from the site.
    reddit = [lead for lead in leads if lead.platform == "reddit"]
    web = [lead for lead in leads if lead.platform == "web"]
    assert reddit and all(lead.handle.startswith("redditor_") and lead.channel == "reddit_dm" for lead in reddit)
    assert web and all(lead.public_email and lead.channel == "email" for lead in web)
    assert {e["stage"] for e in events} >= {"plan", "search", "extract", "dedupe", "research", "qualify", "save"}


async def test_second_run_never_returns_the_same_leads():
    first = await run_agent(RunParams(count=3, platforms=["reddit", "linkedin", "x", "web"]),
                            bd=FakeBrightData(), llm=FakeLLM())
    second = await run_agent(RunParams(count=3, platforms=["reddit", "linkedin", "x", "web"]),
                             bd=FakeBrightData(), llm=FakeLLM())
    a, _ = repo.list_leads(run_id=first["run_id"], include_low_fit=True)
    b, _ = repo.list_leads(run_id=second["run_id"], include_low_fit=True)
    assert a and b
    with get_session() as s:
        keys_a = set(s.exec(select(LeadKey.key).where(LeadKey.lead_id.in_([x.id for x in a]))))
        keys_b = set(s.exec(select(LeadKey.key).where(LeadKey.lead_id.in_([x.id for x in b]))))
    assert keys_a and keys_b and not keys_a & keys_b


async def test_same_search_results_twice_are_all_dropped_as_duplicates():
    fixed = [{"title": "Jane on data entry", "url": "https://x.com/jane/status/1", "snippet": "data entry pain"},
             {"title": "Bob on data entry", "url": "https://x.com/bob/status/2", "snippet": "data entry pain"}]
    first = await run_agent(RunParams(count=2, platforms=["x"]), bd=FakeBrightData(fixed_results=fixed), llm=FakeLLM())
    assert first["qualified"] == 2
    second = await run_agent(RunParams(count=2, platforms=["x"]), bd=FakeBrightData(fixed_results=fixed), llm=FakeLLM())
    assert second["qualified"] == 0
    assert "search rounds" in second["stop_reason"]


async def test_low_fit_leads_are_saved_but_hidden():
    result = await run_agent(RunParams(count=2, platforms=["x"]), bd=FakeBrightData(), llm=FakeLLM(score=3))
    assert result["qualified"] == 0
    visible, _ = repo.list_leads(run_id=result["run_id"])
    everything, _ = repo.list_leads(run_id=result["run_id"], include_low_fit=True)
    assert visible == [] and everything and all(lead.low_fit and not lead.message for lead in everything)


async def test_credit_budget_stops_the_run_gracefully():
    bd = FakeBrightData(max_credits=2)
    result = await run_agent(RunParams(count=10, platforms=["reddit", "web"]), bd=bd, llm=FakeLLM())
    assert repo.get_run(result["run_id"]).status == "completed"
    assert bd.credits_used <= 2
    assert "credit budget" in result["stop_reason"]


async def test_llm_failures_do_not_kill_the_run():
    result = await run_agent(RunParams(count=2, platforms=["x"]), bd=FakeBrightData(),
                             llm=FakeLLM(fail_on={"Outreach"}))
    assert repo.get_run(result["run_id"]).status == "completed"
    assert any("write_outreach failed" in e for e in result["errors"])
    # good leads without a message are NOT saved, so a later run can find them again
    saved, _ = repo.list_leads(run_id=result["run_id"], include_low_fit=True)
    assert saved == []


async def test_category_filter_skips_other_categories():
    result = await run_agent(RunParams(count=2, platforms=["x"], categories=["individual"]),
                             bd=FakeBrightData(), llm=FakeLLM())  # FakeLLM always says "company"
    assert result["qualified"] == 0


class QuotaExhaustedLLM(FakeLLM):
    """Behaves like a Gemini model whose daily quota is used up."""

    def answer(self, schema, messages):
        self.calls.append(schema.__name__)
        raise RuntimeError("429 RESOURCE_EXHAUSTED: Quota exceeded for metric generate_content_free_tier_requests")


async def test_falls_back_to_next_model_when_quota_is_used_up():
    dead, backup = QuotaExhaustedLLM(), FakeLLM()
    result = await run_agent(RunParams(count=2, platforms=["x"]), bd=FakeBrightData(), llm=[dead, backup])
    assert result["qualified"] >= 2
    assert len(dead.calls) == 1  # tried once, then skipped for the rest of the run
    assert backup.calls


async def test_run_stops_early_when_every_model_is_out_of_quota():
    import pytest

    from app.agent.utils import LLMQuotaExhausted

    bd = FakeBrightData()
    with pytest.raises(LLMQuotaExhausted):
        await run_agent(RunParams(count=5, platforms=["reddit", "web"]), bd=bd, llm=[QuotaExhaustedLLM()])
    run = repo.list_runs()[0]
    assert run.status == "failed" and "out of quota" in run.progress
    assert bd.credits_used == 0  # stopped at the planning step: no Bright Data credits wasted
