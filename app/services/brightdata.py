"""Bright Data wrapper: Google search (SERP API) + page fetching (Web Unlocker).

It adds three things on top of the official SDK:
  1. Caching: repeated queries/pages are free (see cache.py).
  2. Credit budget: counts paid requests and stops at MAX_CREDITS_PER_RUN.
  3. Clean output: plain dicts for search results, readable text for pages.

Usage (one instance per agent run):
    async with BrightData() as bd:
        results = await bd.search('site:reddit.com "automate" invoices')
        text = await bd.fetch_page("https://example.com/about")
"""

import logging

import certifi
from bs4 import BeautifulSoup
from brightdata import BrightDataClient

from app.core.config import get_settings
from app.services.cache import cache_get, cache_set, make_key

log = logging.getLogger(__name__)


class CreditLimitReached(Exception):
    """Raised when a run has used up its Bright Data budget."""


class BrightDataError(Exception):
    """Raised when Bright Data returns an unsuccessful result."""


class BrightData:
    def __init__(self, max_credits: int | None = None):
        s = get_settings()
        if not s.brightdata_api_token:
            raise RuntimeError("BRIGHTDATA_API_TOKEN is empty. Add it to .env (see .env.example).")
        self._client = BrightDataClient(
            token=s.brightdata_api_token,
            serp_zone=s.brightdata_serp_zone,
            web_unlocker_zone=s.brightdata_unlocker_zone,
            auto_create_zones=True,  # creates the zones in your account on first use
            # Use certifi's CA bundle: python.org Python on macOS can't see the system certificates.
            ssl_ca_cert=certifi.where(),
        )
        self.max_credits = max_credits or s.max_credits_per_run
        self.credits_used = 0  # paid requests made by this instance
        self.cache_hits = 0  # requests answered from cache (free)
        self.cost_usd = 0.0  # Bright Data's own cost figure, when it reports one

    # "async with BrightData() as bd:" opens and closes the SDK's HTTP session.
    async def __aenter__(self) -> "BrightData":
        try:
            await self._client.__aenter__()  # also checks/creates the SERP + Unlocker zones
        except Exception as e:
            await self._client.__aexit__(None, None, None)
            s = get_settings()
            hint = ""
            if "payment_method_required" in str(e):
                hint = (
                    "\nBright Data needs a payment method on your account before zones can be created by API."
                    "\nEither add one (Billing page), or create the zones yourself in the dashboard"
                    f" (Proxies & Scraping): a 'SERP API' zone named '{s.brightdata_serp_zone}' and a"
                    f" 'Web Unlocker API' zone named '{s.brightdata_unlocker_zone}'"
                    " (or put your zone names in BRIGHTDATA_SERP_ZONE / BRIGHTDATA_UNLOCKER_ZONE in .env)."
                )
            raise RuntimeError(f"Could not connect to Bright Data: {e}{hint}") from e
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.__aexit__(*exc)

    def _spend_one(self) -> None:
        """Check the budget before a paid call, then count it."""
        if self.credits_used >= self.max_credits:
            raise CreditLimitReached(f"Used {self.credits_used}/{self.max_credits} credits this run")
        self.credits_used += 1

    def _record_cost(self, result) -> None:
        if getattr(result, "cost", None):
            self.cost_usd += result.cost

    async def search(self, query: str, num_results: int = 10, time_range: str | None = "m") -> list[dict]:
        """Google search. time_range: "d" day, "w" week, "m" month, "y" year, None = any time.

        Returns: [{"title", "url", "snippet"}, ...]
        """
        key = make_key("serp", q=query, n=num_results, t=time_range)
        if (cached := cache_get(key)) is not None:
            self.cache_hits += 1
            return cached

        self._spend_one()
        extra = {"time_range": time_range} if time_range else {}
        result = await self._client.search.google(query=query, num_results=num_results, **extra)
        self._record_cost(result)
        if not result.success and "502" in str(result.error):
            # Occasional Bright Data/Google hiccup ("redirect location was rejected"): one retry.
            self._spend_one()
            result = await self._client.search.google(query=query, num_results=num_results, **extra)
            self._record_cost(result)
        if not result.success:
            raise BrightDataError(f"Search failed for {query!r}: {result.error}")

        items = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
            for r in (result.data or [])
            if r.get("url")
        ]
        cache_set(key, items)
        return items

    async def fetch_raw(self, url: str) -> str:
        """Fetch any public URL through Web Unlocker and return the raw body (HTML or JSON text)."""
        key = make_key("raw", url=url)
        if (cached := cache_get(key)) is not None:
            self.cache_hits += 1
            return cached

        self._spend_one()
        result = await self._client.scrape_url(url=url)
        self._record_cost(result)
        if not result.success:
            raise BrightDataError(f"Fetch failed for {url}: {result.error}")

        body = result.data if isinstance(result.data, str) else str(result.data)
        cache_set(key, body)
        return body

    async def fetch_page(self, url: str, max_chars: int = 8000) -> str:
        """Fetch any public page and return its visible text (trimmed to max_chars)."""
        return html_to_text(await self.fetch_raw(url))[:max_chars]

    def usage(self) -> dict:
        return {
            "credits_used": self.credits_used,
            "max_credits": self.max_credits,
            "cache_hits": self.cache_hits,
            "cost_usd": round(self.cost_usd, 4),
        }


def html_to_text(html: str) -> str:
    """Strip scripts/styles and collapse whitespace, so the LLM gets only readable text.

    Footers are kept on purpose: that's where public contact emails usually live.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form"]):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)
