"""Unit tests for the small helper functions."""

from app.agent.schemas import Candidate
from app.agent.utils import (
    dedupe_keys,
    domain_of,
    find_public_email,
    infer_profile,
    normalize_url,
    time_range_for,
)


def test_normalize_url():
    assert normalize_url("https://www.LinkedIn.com/in/jane-doe/?utm=1") == "linkedin.com/in/jane-doe"
    assert normalize_url("https://twitter.com/jane") == normalize_url("https://x.com/jane/")
    assert normalize_url("https://old.reddit.com/user/bob") == "reddit.com/user/bob"
    assert normalize_url(None) is None


def test_domain_of():
    assert domain_of("https://www.Acme.com/about") == "acme.com"
    assert domain_of("acme.io") == "acme.io"


def test_infer_profile_from_post_urls():
    x = infer_profile(Candidate(name="J", platform="x", signal="s", source_url="https://x.com/jane_d/status/99"))
    assert x.handle == "jane_d" and x.profile_url == "https://x.com/jane_d"
    li = infer_profile(Candidate(name="J", platform="linkedin", signal="s",
                                 source_url="https://www.linkedin.com/posts/jane-doe-123_we-are-hiring-activity-1"))
    assert li.profile_url == "https://www.linkedin.com/in/jane-doe-123"


def test_dedupe_keys_cover_profile_handle_and_domain():
    c = Candidate(name="J", platform="x", handle="@Jane", profile_url="https://twitter.com/Jane",
                  company_website="https://www.acme.com", signal="s", source_url="https://x.com/Jane/status/1")
    keys = dedupe_keys(c)
    assert "profile:x.com/Jane" in keys and "handle:x:jane" in keys and "domain:acme.com" in keys


def test_dedupe_keys_ignore_platform_domains_and_fall_back_to_post():
    c = Candidate(name="anon", platform="reddit", company_website="https://reddit.com/r/x",
                  signal="s", source_url="https://www.reddit.com/r/x/comments/1/t/")
    assert dedupe_keys(c) == ["post:reddit.com/r/x/comments/1/t"]


def test_find_public_email_prefers_company_domain():
    html = "<a href='mailto:hi@gmail.com'>x</a> contact: Sales@Acme.com <img src='logo@2x.png'>"
    assert find_public_email(html, "https://acme.com") == "sales@acme.com"
    assert find_public_email("no email here") is None


def test_time_range_for():
    assert [time_range_for(d) for d in (1, 7, 30, 90, 400)] == ["d", "w", "m", "y", None]
