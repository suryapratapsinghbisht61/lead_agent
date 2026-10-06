"""Phase 1 tests: no network, no API keys needed."""

from app.core.config import get_settings, load_profile
from app.services.brightdata import html_to_text
from app.services.cache import cache_get, cache_set, make_key


def test_settings_have_defaults():
    s = get_settings()
    assert s.max_credits_per_run > 0
    assert s.llm_provider


def test_profile_loads():
    profile = load_profile()
    assert profile["me"]["name"]
    assert profile["services"]


def test_cache_key_is_stable_and_order_independent():
    assert make_key("serp", q="a", n=5) == make_key("serp", n=5, q="a")
    assert make_key("serp", q="a") != make_key("serp", q="b")


def test_cache_roundtrip():
    key = make_key("test", x=1)
    cache_set(key, [{"url": "https://x.com"}], ttl_hours=1)
    assert cache_get(key) == [{"url": "https://x.com"}]


def test_html_to_text_strips_scripts_keeps_footer():
    html = "<html><script>evil()</script><p>Hello</p><footer>hi@acme.com</footer></html>"
    text = html_to_text(html)
    assert "evil" not in text
    assert "Hello" in text and "hi@acme.com" in text
