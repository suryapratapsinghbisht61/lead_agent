"""Smoke-test the Streamlit dashboard headlessly (no browser) in demo mode."""

from streamlit.testing.v1 import AppTest

from app.core import config
from app.core.config import ROOT_DIR

APP = str(ROOT_DIR / "dashboard" / "streamlit_app.py")


def set_users(monkeypatch, value: str) -> None:
    monkeypatch.setenv("DASHBOARD_USERS", value)
    config.get_settings.cache_clear()  # settings are cached; re-read them with the new value


def login(at: AppTest, user_id: str, password: str) -> AppTest:
    at.text_input[0].input(user_id)
    at.text_input[1].input(password)
    at.button[0].click()
    return at.run()


def test_dashboard_requires_login(monkeypatch):
    set_users(monkeypatch, "user1:secret")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.title[0].value == "🔒 Lead Agent"
    assert not at.sidebar.radio  # nothing else is shown before login

    login(at, "user1", "wrong")
    assert any("Wrong ID or password" in e.value for e in at.error)
    assert not at.sidebar.radio


def test_dashboard_without_users_configured_stays_locked(monkeypatch):
    set_users(monkeypatch, "")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert any("No users configured" in e.value for e in at.error)


def test_dashboard_demo_run_and_pages(monkeypatch):
    set_users(monkeypatch, "user1:secret")
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["demo"] = True
    at.run()
    login(at, "user1", "secret")
    assert not at.exception

    # Fill the run form and submit
    at.sidebar.radio[0].set_value("Find leads")
    at.run()
    at.number_input[0].set_value(2)
    next(b for b in at.button if b.label == "Run agent").click()
    at.run()
    assert not at.exception
    assert any("Qualified" == m.label for m in at.metric)

    # Other pages render
    for page in ("Leads", "Runs"):
        at.sidebar.radio[0].set_value(page)
        at.run()
        assert not at.exception, page
