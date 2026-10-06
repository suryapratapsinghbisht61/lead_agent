"""Data shapes used by the agent.

Two kinds of models live here:
  * LLM output schemas (QueryPlan, CandidateList, Qualification, Outreach):
    passed to llm.with_structured_output(...) so the model must return exactly
    these fields. No free-text parsing anywhere.
  * Internal models (RunParams, Lead): how we pass data between nodes.
"""

from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["reddit", "linkedin", "x", "web"]
Category = Literal["startup", "company", "individual"]
Channel = Literal["linkedin_note", "x_dm", "reddit_dm", "email", "website_contact"]

ALL_PLATFORMS: list[str] = ["reddit", "linkedin", "x", "web"]
ALL_CATEGORIES: list[str] = ["startup", "company", "individual"]


# ---------------------------------------------------------------- run input
class RunParams(BaseModel):
    """What the user asked for in this run."""

    count: int = Field(default=10, ge=1, le=50, description="How many qualified leads to find")
    niche: str | None = Field(default=None, description='e.g. "e-commerce"')
    keywords: list[str] = Field(default_factory=list, description="Extra words to include in searches")
    categories: list[Category] = Field(default_factory=lambda: list(ALL_CATEGORIES))
    platforms: list[Platform] = Field(default_factory=lambda: list(ALL_PLATFORMS))
    days: int = Field(default=30, ge=1, le=365, description="Only signals from the last N days")
    max_credits: int | None = Field(default=None, description="Override MAX_CREDITS_PER_RUN")


# ---------------------------------------------------------------- LLM outputs
class SearchQuery(BaseModel):
    platform: Platform
    query: str = Field(description="Google search words only, WITHOUT any site: operator")
    reason: str = Field(description="Which signal this query is hunting for")


class QueryPlan(BaseModel):
    queries: list[SearchQuery]


class Candidate(BaseModel):
    name: str = Field(description="Person or company name as shown; use the handle if no name")
    handle: str | None = Field(default=None, description="Username/handle without @ or u/, if visible")
    profile_url: str | None = Field(default=None, description="Their profile URL if visible")
    company: str | None = None
    company_website: str | None = Field(default=None, description="Company homepage URL if mentioned")
    platform: Platform
    signal: str = Field(description="The exact complaint/hiring post/quote that shows the pain (1-2 sentences)")
    source_url: str = Field(description="URL of the search result this came from (copy exactly)")


class CandidateList(BaseModel):
    candidates: list[Candidate]


class Qualification(BaseModel):
    category: Category
    pain_points: list[str] = Field(description="Specific problems our services could solve; empty if none")
    fit_score: int = Field(ge=1, le=10, description="1 = no fit, 10 = perfect fit")
    fit_reason: str = Field(description="One line explaining the score")
    name: str | None = Field(default=None, description="Better name for the lead if the notes reveal one")
    company: str | None = Field(default=None, description="Company name if the notes reveal one")


class Outreach(BaseModel):
    about_them: str = Field(description="2-3 sentences: what this person or company does")
    how_i_can_help: str = Field(description="2-3 sentences: which service fits and what we would build")
    subject: str | None = Field(default=None, description="Email subject line (only for the email channel)")
    message: str = Field(description="The outreach message, under 100 words")


# ---------------------------------------------------------------- internal
class Lead(BaseModel):
    """One lead as it moves through research -> qualify -> write_outreach."""

    candidate: Candidate
    dedupe_keys: list[str] = Field(default_factory=list)
    research_notes: str = ""
    public_email: str | None = None
    qualification: Qualification | None = None
    channel: Channel | None = None
    outreach: Outreach | None = None
    skipped_reason: str | None = None  # e.g. "duplicate author", "outside date range"

    def is_qualified(self, min_score: int) -> bool:
        return (
            self.skipped_reason is None
            and self.qualification is not None
            and self.qualification.fit_score >= min_score
            and self.outreach is not None
        )
