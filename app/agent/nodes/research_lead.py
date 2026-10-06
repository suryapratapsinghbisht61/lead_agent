"""Per-lead step 1: light research through Bright Data (no LLM here).

Collects into lead.research_notes:
  * the original post (Reddit JSON gives the author + date; other sites give page text)
  * the company homepage, if we know it, plus any public email printed on it
If a fetch fails or the credit budget is used up, we keep going with what we have.
"""

import json
import logging
import re
from datetime import datetime, timezone

from langgraph.runtime import Runtime

from app.agent.state import LeadState, RunContext
from app.agent.utils import dedupe_keys, emit, find_public_email
from app.db import repo
from app.services.brightdata import CreditLimitReached, html_to_text

log = logging.getLogger(__name__)

MAX_NOTES_CHARS = 7000


async def fetch_reddit_post(bd, url: str) -> dict | None:
    """Reddit serves any public post as JSON if you add .json to its URL."""
    m = re.search(r"(/r/[^/]+/comments/[^/?#]+)", url)
    if not m:
        return None
    raw = await bd.fetch_raw(f"https://www.reddit.com{m.group(1)}/.json")
    data = json.loads(raw)
    post = data[0]["data"]["children"][0]["data"]
    return {
        "author": post.get("author"),
        "title": post.get("title", ""),
        "text": post.get("selftext", ""),
        "subreddit": post.get("subreddit", ""),
        "created": datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc),
    }


async def research_lead(state: LeadState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    params = state["params"]
    lead = state["lead"].model_copy(deep=True)  # never mutate shared state in place
    c = lead.candidate
    notes: list[str] = [f"Signal (from search): {c.signal}"]
    errors: list[str] = []
    emit("research", f"Researching {c.name} ({c.platform})")

    # 1) The post / page where we found them
    try:
        post = None
        if c.platform == "reddit":
            try:
                post = await fetch_reddit_post(ctx.bd, c.source_url)
            except (ValueError, KeyError, IndexError, TypeError):
                post = None  # JSON not available, fall back to the HTML page below
        if post:
            age_days = (datetime.now(timezone.utc) - post["created"]).days
            if age_days > params.days:
                lead.skipped_reason = f"post is {age_days} days old (limit {params.days})"
                return {"lead": lead}
            if post["author"] and post["author"] not in ("[deleted]", "AutoModerator"):
                c.handle = post["author"]
                c.profile_url = f"https://www.reddit.com/user/{post['author']}"
                if c.name.lower().startswith("reddit user"):
                    c.name = f"u/{post['author']}"
                new_keys = [k for k in dedupe_keys(c) if k not in lead.dedupe_keys]
                if repo.existing_keys(new_keys):
                    lead.skipped_reason = "duplicate: this Reddit author is already in the database"
                    return {"lead": lead}
                lead.dedupe_keys += new_keys
            notes.append(f"Post in r/{post['subreddit']} ({age_days} days ago)\n"
                         f"Title: {post['title']}\n{post['text'][:3000]}")
        else:
            page = await ctx.bd.fetch_page(c.source_url, max_chars=3500)
            notes.append(f"Source page text:\n{page}")
    except CreditLimitReached:
        notes.append("(Credit budget reached: using the search snippet only.)")
    except Exception as e:
        errors.append(f"research: could not fetch post for {c.name}: {e}")

    # 2) The company website (homepage), plus any public email printed on it
    if c.company_website:
        try:
            raw = await ctx.bd.fetch_raw(c.company_website)
            lead.public_email = find_public_email(raw, c.company_website)
            notes.append(f"Company website ({c.company_website}):\n{html_to_text(raw)[:3000]}")
        except CreditLimitReached:
            pass
        except Exception as e:
            errors.append(f"research: could not fetch website {c.company_website}: {e}")

    lead.research_notes = "\n\n".join(notes)[:MAX_NOTES_CHARS]
    return {"lead": lead, "errors": errors}
