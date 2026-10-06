"""Fake LLM + fake Bright Data: run the whole agent with no keys, no network, no credits (tests + --demo mode).

They return believable, deterministic data shaped exactly like the real thing.
"""

import hashlib
import itertools
import json
import re
import time

from app.agent.schemas import (
    Candidate,
    CandidateList,
    Outreach,
    Qualification,
    QueryPlan,
    SearchQuery,
)
from app.services.brightdata import CreditLimitReached

_query_counter = itertools.count(1)  # global, so every planned query is unique across runs


def _h(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def _text_of(messages) -> str:
    return "\n".join(str(m.content) for m in messages)


# ------------------------------------------------------------------ LLM
class FakeLLM:
    """Mimics llm.with_structured_output(Schema).ainvoke(messages)."""

    def __init__(self, fail_on: set[str] | None = None, score: int | None = None):
        self.fail_on = fail_on or set()  # schema names that should raise (to test error handling)
        self.score = score  # force a fit score
        self.calls: list[str] = []

    def with_structured_output(self, schema):
        return _FakeStructured(self, schema)

    def answer(self, schema, messages):
        name = schema.__name__
        self.calls.append(name)
        if name in self.fail_on:
            raise RuntimeError(f"fake LLM failure for {name}")
        text = _text_of(messages)

        if schema is QueryPlan:
            platforms = re.search(r"Platforms: (.+)", text).group(1).split(", ")
            return QueryPlan(queries=[
                SearchQuery(platform=p, query=f'"manual data entry" q{next(_query_counter)}', reason="test")
                for p in platforms
            ])

        if schema is CandidateList:
            blocks = re.findall(r"platform: (\w+)\nTitle: (.*)\nURL: (\S+)", text)
            return CandidateList(candidates=[
                Candidate(name=title.split(" ")[0] or "Someone", platform=platform, source_url=url,
                          signal="Spending hours on manual data entry every week",
                          company_website=f"https://acme-{_h(url)}.com" if platform == "web" else None)
                for platform, title, url in blocks
            ])

        if schema is Qualification:
            score = self.score if self.score is not None else (8 if "data entry" in text else 3)
            return Qualification(category="company", pain_points=["manual data entry"], fit_score=score,
                                 fit_reason="Clear repetitive data-entry pain")

        if schema is Outreach:
            return Outreach(about_them="They run a small business.",
                            how_i_can_help="An automation that removes their data entry.",
                            subject="Quick idea about your data entry", message="Hi, saw your post. Open to a quick call?")
        raise ValueError(f"FakeLLM has no answer for {name}")


class _FakeStructured:
    def __init__(self, llm: FakeLLM, schema):
        self.llm, self.schema = llm, schema

    async def ainvoke(self, messages):
        return self.llm.answer(self.schema, messages)


# ------------------------------------------------------------------ Bright Data
class FakeBrightData:
    """Same interface as app.services.brightdata.BrightData."""

    def __init__(self, max_credits: int = 1000, fixed_results: list[dict] | None = None, results_per_query: int = 3):
        self.max_credits = max_credits
        self.credits_used = 0
        self.cache_hits = 0
        self.fixed_results = fixed_results  # if set, every search returns exactly these
        self.results_per_query = results_per_query
        self.searches: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def _spend(self):
        if self.credits_used >= self.max_credits:
            raise CreditLimitReached("fake budget")
        self.credits_used += 1

    async def search(self, query: str, num_results: int = 10, time_range: str | None = "m") -> list[dict]:
        self._spend()
        self.searches.append(query)
        if self.fixed_results is not None:
            return list(self.fixed_results)
        h = _h(query)
        if "-site:reddit.com" in query:  # the "web" platform excludes the social sites
            urls = [f"https://blog-{h}{i}.com/our-ops-story" for i in range(self.results_per_query)]
        elif "site:reddit.com" in query:
            urls = [f"https://www.reddit.com/r/smallbusiness/comments/{h}{i}/help_automating/" for i in range(self.results_per_query)]
        elif "linkedin" in query:
            urls = [f"https://www.linkedin.com/posts/founder-{h}{i}_automation-activity-1" for i in range(self.results_per_query)]
        elif "x.com" in query:
            urls = [f"https://x.com/founder{h}{i}/status/123" for i in range(self.results_per_query)]
        else:
            raise ValueError(f"unexpected query {query}")
        return [{"title": f"Person{h}{i} on manual work", "url": u, "snippet": "drowning in data entry"}
                for i, u in enumerate(urls)]

    async def fetch_raw(self, url: str) -> str:
        self._spend()
        if url.endswith(".json"):
            post_id = re.search(r"comments/([^/]+)", url).group(1)
            return json.dumps([{"data": {"children": [{"data": {
                "author": f"redditor_{post_id}", "title": "How do I automate data entry?",
                "selftext": "I spend 10 hours a week on manual data entry for my shop.",
                "subreddit": "smallbusiness", "created_utc": time.time() - 3 * 86400}}]}}])
        return f"<html><body><p>We are a growing team.</p><footer>hello@{url.split('//')[1].split('/')[0]}</footer></body></html>"

    async def fetch_page(self, url: str, max_chars: int = 8000) -> str:
        from app.services.brightdata import html_to_text

        return html_to_text(await self.fetch_raw(url))[:max_chars]

    def usage(self) -> dict:
        return {"credits_used": self.credits_used, "max_credits": self.max_credits,
                "cache_hits": self.cache_hits, "cost_usd": 0.0}
