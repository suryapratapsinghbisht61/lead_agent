"""Smoke-test the Streamlit dashboard headlessly (no browser) in demo mode."""

from streamlit.testing.v1 import AppTest

from app.core.config import ROOT_DIR

APP = str(ROOT_DIR / "dashboard" / "streamlit_app.py")


def test_dashboard_demo_run_and_pages():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["demo"] = True
    at.run()
    assert not at.exception

    # Fill the run form and submit
    at.sidebar.radio[0].set_value("Find leads")
    at.run()
    at.number_input[0].set_value(2)
    at.button[0].click()
    at.run()
    assert not at.exception
    assert any("Qualified" == m.label for m in at.metric)

    # Other pages render
    for page in ("Leads", "Runs"):
        at.sidebar.radio[0].set_value(page)
        at.run()
        assert not at.exception, page
