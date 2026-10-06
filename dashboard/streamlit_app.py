"""Streamlit dashboard: run the agent, browse leads, copy messages, track outreach.

    uv run streamlit run dashboard/streamlit_app.py

Streamlit re-runs this whole file top to bottom on every click; st.session_state
keeps values between those re-runs. It calls the agent directly (no API needed).
"""

import asyncio
import os

import pandas as pd
import streamlit as st

from app.agent.schemas import ALL_CATEGORIES, ALL_PLATFORMS, RunParams
from app.core import config
from app.core.config import ROOT_DIR
from app.db import session as db_session
from app.db.models import OUTREACH_STATUSES

st.set_page_config(page_title="Lead Agent", page_icon="🎯", layout="wide")

# ------------------------------------------------------------------ demo mode switch
demo = st.sidebar.toggle("Demo mode (fake data, no API keys)", value=st.session_state.get("demo", False),
                         help="Uses a fake LLM and fake search results, stored in data/demo.db.")
if demo != st.session_state.get("demo_applied"):
    if demo:
        os.environ["DATABASE_URL"] = f"sqlite:///{ROOT_DIR / 'data' / 'demo.db'}"
        os.environ["EXPORT_DIR"] = str(ROOT_DIR / "exports" / "demo")
    else:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("EXPORT_DIR", None)
    config.get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    st.session_state["demo"] = st.session_state["demo_applied"] = demo

from app.db import repo  # noqa: E402  (after the DB switch above)
from app.services.export import leads_to_xlsx  # noqa: E402

db_session.init_db()
settings = config.get_settings()
st.sidebar.caption(f"LLM: `{settings.llm_provider}/{settings.llm_model}`" if not demo else "Running on fake data")
page = st.sidebar.radio("Go to", ["Leads", "Find leads", "Runs"], key="page")


# ------------------------------------------------------------------ helpers
def run_agent_with_ui(params: RunParams) -> dict | None:
    from app.agent.runner import run_agent

    extra = {}
    if demo:
        from app.agent.fakes import FakeBrightData, FakeLLM

        extra = {"bd": FakeBrightData(), "llm": FakeLLM()}

    bar = st.progress(0.0, text="Starting...")
    with st.status("Agent running...", expanded=True) as status:

        def on_progress(event: dict) -> None:
            status.write(f"**{event.get('stage', '')}**: {event.get('message', '')}")
            if "qualified" in event and event.get("target"):
                done = min(event["qualified"] / event["target"], 1.0)
                bar.progress(done, text=f"{event['qualified']}/{event['target']} qualified leads")

        try:
            result = asyncio.run(run_agent(params, on_progress=on_progress, **extra))
        except Exception as e:
            status.update(label=f"Run failed: {e}", state="error")
            return None
        bar.progress(1.0, text="Done")
        status.update(label=f"Done: {result['qualified']} qualified leads", state="complete", expanded=False)
    return result


def excel_view(leads) -> pd.DataFrame:
    """Every column, same as the Excel export."""
    from app.services.export import COLUMNS, _value

    return pd.DataFrame([{title: _value(lead, attr) for title, attr, _ in COLUMNS} for lead in leads])


LINK_COLUMNS = {c: st.column_config.LinkColumn(c) for c in ("Profile URL", "Website", "Source URL")}


def leads_dataframe(leads) -> pd.DataFrame:
    return pd.DataFrame([{
        "ID": lead.id, "Fit": lead.fit_score, "Name": lead.name, "Company": lead.company or "",
        "Category": lead.category or "", "Platform": lead.platform, "Channel": lead.channel or "",
        "Status": lead.status, "Why": lead.fit_reason, "Found": lead.created_at.strftime("%Y-%m-%d"),
    } for lead in leads])


def lead_detail(lead_id: int) -> None:
    lead = repo.get_lead(lead_id)
    if lead is None:
        return
    st.divider()
    head, meta = st.columns([3, 1])
    head.subheader(f"{lead.name}" + (f" @ {lead.company}" if lead.company else ""))
    head.caption(f"{lead.category} · {lead.platform} · fit {lead.fit_score}/10 · {lead.fit_reason}")
    links = [f"[Profile]({lead.profile_url})" if lead.profile_url else "",
             f"[Source post]({lead.source_url})" if lead.source_url else "",
             f"[Website]({lead.company_website})" if lead.company_website else "",
             f"Email: `{lead.public_email}`" if lead.public_email else ""]
    head.markdown(" · ".join(x for x in links if x))
    meta.metric("Fit score", f"{lead.fit_score}/10")

    left, right = st.columns(2)
    with left:
        st.markdown("**Signal that flagged them**")
        st.info(lead.signal or "-")
        st.markdown("**About them**")
        st.write(lead.about_them or "-")
        st.markdown("**How I can help**")
        st.write(lead.how_i_can_help or "-")
        if lead.pain_points:
            st.markdown("**Pain points**")
            st.markdown("\n".join(f"- {p}" for p in lead.pain_points))
    with right:
        st.markdown(f"**Message** ({lead.channel or 'n/a'}): use the copy icon at the top-right")
        if lead.subject:
            st.code(lead.subject, language=None)
        st.code(lead.message or "(no message: low-fit lead)", language=None, wrap_lines=True)
        with st.form(f"track_{lead.id}"):
            status = st.selectbox("Outreach status", OUTREACH_STATUSES, index=OUTREACH_STATUSES.index(lead.status))
            notes = st.text_area("Notes", value=lead.notes)
            if st.form_submit_button("Save"):
                repo.update_lead(lead.id, status=status, notes=notes)
                st.toast("Saved")
                st.rerun()


# ------------------------------------------------------------------ pages
if page == "Find leads":
    st.title("🎯 Find leads")
    with st.form("run"):
        c1, c2, c3 = st.columns(3)
        count = c1.number_input("How many qualified leads", 1, 50, 10)
        niche = c2.text_input("Niche (optional)", placeholder="e.g. e-commerce")
        keywords = c3.text_input("Extra keywords (comma-separated)")
        c4, c5 = st.columns(2)
        categories = c4.multiselect("Lead types", ALL_CATEGORIES, default=ALL_CATEGORIES)
        platforms = c5.multiselect("Platforms", ALL_PLATFORMS, default=ALL_PLATFORMS)
        c6, c7 = st.columns(2)
        days = c6.slider("Only signals from the last N days", 1, 365, 30)
        max_credits = c7.number_input("Bright Data credit budget", 10, 5000, settings.max_credits_per_run, step=10)
        submitted = st.form_submit_button("Run agent", type="primary")

    if submitted:
        if not categories or not platforms:
            st.error("Pick at least one lead type and one platform.")
        else:
            params = RunParams(count=count, niche=niche or None, categories=categories, platforms=platforms, days=days,
                               keywords=[k.strip() for k in keywords.split(",") if k.strip()], max_credits=max_credits)
            result = run_agent_with_ui(params)
            if result:
                st.session_state["last_run"] = result["run_id"]
                u = result["usage"]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Qualified", result["qualified"])
                m2.metric("Low fit (hidden)", result["low_fit_saved"])
                m3.metric("Credits used", f"{u['credits_used']}/{u['max_credits']}")
                m4.metric("Cache hits", u["cache_hits"])
                st.caption(f"Stopped because: {result['stop_reason']}")
                if result["errors"]:
                    with st.expander(f"{len(result['errors'])} non-fatal errors"):
                        st.write(result["errors"])

    if run_id := st.session_state.get("last_run"):
        leads, _ = repo.list_leads(run_id=run_id)
        if leads:
            st.subheader("Leads from this run")
            event = st.dataframe(leads_dataframe(leads), hide_index=True, on_select="rerun",
                                 selection_mode="single-row", key="run_table")
            if event.selection.rows:
                lead_detail(leads[event.selection.rows[0]].id)

elif page == "Leads":
    st.title("📋 All leads")
    f1, f2, f3, f4 = st.columns(4)
    cats = f1.multiselect("Category", ALL_CATEGORIES)
    plats = f2.multiselect("Platform", ALL_PLATFORMS)
    stats = f3.multiselect("Status", OUTREACH_STATUSES)
    min_score = f4.slider("Min fit score", 1, 10, 1)
    g1, g2 = st.columns([3, 1])
    search = g1.text_input("Search name / company / signal")
    low_fit = g2.toggle("Include low-fit leads")

    leads, total = repo.list_leads(categories=cats or None, platforms=plats or None, statuses=stats or None,
                                   min_score=min_score, include_low_fit=low_fit, search=search or None, limit=1000)
    st.caption(f"{total} leads")
    if leads:
        st.download_button("Download Excel", leads_to_xlsx(leads), "leads.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        tab_sheet, tab_detail = st.tabs(["📊 Excel view (all columns)", "🔍 Lead details + copy message"])
        with tab_sheet:
            st.dataframe(excel_view(leads), hide_index=True, column_config=LINK_COLUMNS, height=600)
        with tab_detail:
            event = st.dataframe(leads_dataframe(leads), hide_index=True, on_select="rerun",
                                 selection_mode="single-row", key="all_table")
            if event.selection.rows:
                lead_detail(leads[event.selection.rows[0]].id)
            else:
                st.caption("Click a row to see the full lead and its message.")
    else:
        st.info("No leads yet. Go to **Find leads** to run the agent.")

else:
    st.title("🕑 Run history")
    runs = repo.list_runs(100)
    if not runs:
        st.info("No runs yet.")
    for r in runs:
        icon = {"completed": "✅", "failed": "❌", "running": "⏳", "queued": "🕐"}.get(r.status, "")
        with st.expander(f"{icon} {r.created_at:%Y-%m-%d %H:%M} · {r.qualified_count} qualified · "
                         f"{r.credits_used} credits · {r.id}"):
            st.json(r.params)
            st.write(f"**Status:** {r.status} · **Stop reason:** {r.stop_reason or r.progress}")
            if r.errors:
                st.write("**Errors:**", r.errors[:20])
            run_leads, _ = repo.list_leads(run_id=r.id, limit=1000)
            if run_leads:
                st.download_button("Download this run (Excel)", leads_to_xlsx(run_leads), f"leads_{r.id}.xlsx",
                                   key=f"dl_{r.id}")
