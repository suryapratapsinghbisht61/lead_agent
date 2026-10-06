"""Small helpers shared by the nodes (no LLM prompts here)."""

import logging
import re
import time
from urllib.parse import urlparse

from langgraph.config import get_stream_writer
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.agent.schemas import Candidate

log = logging.getLogger(__name__)

# The site: filter added to each query, per platform.
SITE_FILTERS = {
    "reddit": "site:reddit.com",
    "linkedin": "(site:linkedin.com/posts OR site:linkedin.com/jobs)",
    "x": "(site:x.com OR site:twitter.com)",
    "web": "-site:reddit.com -site:linkedin.com -site:x.com -site:twitter.com -site:youtube.com",
}


# ------------------------------------------------------------------ progress
def emit(stage: str, message: str, **extra) -> None:
    """Send a progress event to whoever is streaming the graph (CLI, dashboard, worker)."""
    log.info("[%s] %s", stage, message)
    try:
        get_stream_writer()({"stage": stage, "message": message, **extra})
    except RuntimeError:  # called outside a running graph (e.g. in a unit test)
        pass


# ------------------------------------------------------------------ LLM calls
class StructuredOutputError(Exception):
    pass


class LLMQuotaExhausted(Exception):
    """Every configured model hit its quota. Nodes re-raise this so the run stops
    instead of spending Bright Data credits on leads we can't qualify."""


_EXHAUSTED_FOR_SECONDS = 3600  # after a quota error, skip that model for an hour
_exhausted_until: dict[int, float] = {}  # id(model) -> time when we may try it again


def is_quota_error(e: Exception) -> bool:
    text = str(e)
    return "RESOURCE_EXHAUSTED" in text or "429" in text or "quota" in text.lower()


@retry(
    retry=retry_if_exception_type((ValidationError, StructuredOutputError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=8),
    reraise=True,
)
async def _structured_once(llm, schema: type[BaseModel], messages: list) -> BaseModel:
    """One model, retried if it returns malformed output (small models do this sometimes)."""
    result = await llm.with_structured_output(schema).ainvoke(messages)
    if result is None:
        raise StructuredOutputError(f"Model returned nothing for {schema.__name__}")
    if isinstance(result, dict):  # some providers return a dict instead of the model
        result = schema.model_validate(result)
    return result


async def structured_call(llm, schema: type[BaseModel], messages: list) -> BaseModel:
    """Ask the LLM for an instance of `schema`.

    `llm` can be one model or a list [main, *fallbacks]. If a model's quota is used up,
    we mark it and move on to the next one. Network retries are handled by the model itself.
    """
    models = llm if isinstance(llm, list) else [llm]
    last_error: Exception | None = None
    for model in models:
        if _exhausted_until.get(id(model), 0) > time.time():
            continue
        try:
            return await _structured_once(model, schema, messages)
        except Exception as e:
            if not is_quota_error(e):
                raise
            name = getattr(model, "model", "model")
            log.warning("LLM quota exhausted for %s, switching to the next model", name)
            _exhausted_until[id(model)] = time.time() + _EXHAUSTED_FOR_SECONDS
            last_error = e
    raise LLMQuotaExhausted(
        "All configured LLM models are out of quota (free tiers have small daily limits). "
        "Wait for the quota to reset, add models to LLM_FALLBACK_MODELS, or switch LLM_PROVIDER. "
        f"Last error: {str(last_error)[:200]}"
    )


# ------------------------------------------------------------------ URLs / dedupe
def domain_of(url: str | None) -> str | None:
    """'https://www.Acme.com/about' -> 'acme.com'"""
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host or None


def normalize_url(url: str | None) -> str | None:
    """Lowercase host, drop scheme/www/query/fragment/trailing slash; unify twitter.com -> x.com."""
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("old.")
    if host == "twitter.com":
        host = "x.com"
    path = p.path.rstrip("/")
    return f"{host}{path}" if host else None


def infer_profile(c: Candidate) -> Candidate:
    """Fill handle/profile_url from the post URL when the URL format reveals the author."""
    url = c.source_url or ""
    if not c.handle:
        # x.com/<handle>/status/123
        if m := re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/", url):
            c.handle = m.group(1)
        # linkedin.com/posts/<vanity-name>_some-title-activity-123
        elif m := re.search(r"linkedin\.com/posts/([A-Za-z0-9\-]+?)_", url):
            c.handle = m.group(1)
    if c.handle and not c.profile_url:
        if c.platform == "x":
            c.profile_url = f"https://x.com/{c.handle}"
        elif c.platform == "linkedin" and "linkedin.com/posts/" in url:
            c.profile_url = f"https://www.linkedin.com/in/{c.handle}"
        elif c.platform == "reddit":
            c.profile_url = f"https://www.reddit.com/user/{c.handle}"
    return c


# Sites where a "company_website" is really just a platform page, not a company domain.
_NOT_COMPANY_DOMAINS = {"reddit.com", "linkedin.com", "x.com", "twitter.com", "youtube.com", "medium.com",
                        "facebook.com", "instagram.com", "github.com", "google.com"}


def dedupe_keys(c: Candidate) -> list[str]:
    """Every identity this lead could be recognised by later. A lead matching ANY key is a duplicate."""
    keys: list[str] = []
    if url := normalize_url(c.profile_url):
        keys.append(f"profile:{url}")
    if c.handle:
        keys.append(f"handle:{c.platform}:{c.handle.lower().lstrip('@').removeprefix('u/')}")
    domain = domain_of(c.company_website)
    if domain and domain not in _NOT_COMPANY_DOMAINS:
        keys.append(f"domain:{domain}")
    if not keys:  # anonymous post: at least never process the same post twice
        keys.append(f"post:{normalize_url(c.source_url)}")
    return keys


# ------------------------------------------------------------------ emails / dates
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_JUNK_EMAIL = ("example.", "sentry", "wixpress", "noreply", "no-reply", ".png", ".jpg", ".svg", ".webp", "@2x")


def find_public_email(text: str, website: str | None = None) -> str | None:
    """Pick a contact email that is literally printed on the page. Prefers the company's own domain."""
    emails = [e.strip(".").lower() for e in _EMAIL_RE.findall(text or "")]
    emails = [e for e in dict.fromkeys(emails) if not any(j in e for j in _JUNK_EMAIL)]
    if not emails:
        return None
    domain = domain_of(website)
    if domain:
        own = [e for e in emails if e.endswith("@" + domain) or e.endswith("." + domain)]
        if own:
            return own[0]
    return emails[0]


def time_range_for(days: int) -> str | None:
    """Map 'last N days' to Google's time filter (day/week/month/year)."""
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    if days <= 366:
        return "y"
    return None
