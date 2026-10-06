"""Run the lead agent from the terminal.

    uv run python scripts/run_cli.py --count 5 --niche "e-commerce"
    uv run python scripts/run_cli.py --count 10 --platforms reddit linkedin --categories startup company
    uv run python scripts/run_cli.py --demo          # fake data, no API keys needed
    uv run python scripts/run_cli.py --show-graph    # print the graph diagram (Mermaid)
"""

import argparse
import asyncio
import os
import sys
import textwrap

from app.agent.schemas import ALL_CATEGORIES, ALL_PLATFORMS, RunParams
from app.core.config import ROOT_DIR, get_settings
from app.core.logging import setup_logging


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Find, research and draft outreach for qualified leads.")
    p.add_argument("--count", type=int, default=10, help="qualified leads to find (default 10)")
    p.add_argument("--niche", help='e.g. "e-commerce", "dental clinics"')
    p.add_argument("--keywords", nargs="*", default=[], help="extra search words")
    p.add_argument("--categories", nargs="*", default=ALL_CATEGORIES, choices=ALL_CATEGORIES)
    p.add_argument("--platforms", nargs="*", default=ALL_PLATFORMS, choices=ALL_PLATFORMS)
    p.add_argument("--days", type=int, default=30, help="only signals from the last N days (default 30)")
    p.add_argument("--max-credits", type=int, help="Bright Data budget for this run")
    p.add_argument("--demo", action="store_true", help="use fake LLM + fake Bright Data (no keys, no cost)")
    p.add_argument("--show-graph", action="store_true", help="print the LangGraph diagram and exit")
    p.add_argument("--verbose", action="store_true", help="show detailed logs")
    return p.parse_args()


def print_progress(event: dict) -> None:
    print(f"  [{event.get('stage', ''):8}] {event.get('message', '')}")
    for q in event.get("queries", []):
        print(f"             - {q}")


def print_leads(run_id: str) -> None:
    from app.db import repo

    leads, _ = repo.list_leads(run_id=run_id, limit=500)
    for i, lead in enumerate(sorted(leads, key=lambda r: -r.fit_score), 1):
        print("\n" + "=" * 80)
        print(f"{i}. {lead.name}" + (f" @ {lead.company}" if lead.company else "")
              + f"   [{lead.category} | {lead.platform} | fit {lead.fit_score}/10]")
        print(f"   Why: {lead.fit_reason}")
        print(f"   Link: {lead.profile_url or lead.source_url}" + (f"   Email: {lead.public_email}" if lead.public_email else ""))
        print("\n   About them: " + textwrap.fill(lead.about_them, 76, subsequent_indent="   "))
        print("\n   How I can help: " + textwrap.fill(lead.how_i_can_help, 76, subsequent_indent="   "))
        print(f"\n   Message ({lead.channel}):")
        if lead.subject:
            print(f"   Subject: {lead.subject}")
        print(textwrap.indent(lead.message, "   | "))


async def main() -> int:
    args = parse_args()
    if args.demo:  # keep fake leads out of your real database and exports
        os.environ["DATABASE_URL"] = f"sqlite:///{ROOT_DIR / 'data' / 'demo.db'}"
        os.environ["EXPORT_DIR"] = str(ROOT_DIR / "exports" / "demo")
    setup_logging("DEBUG" if args.verbose else "WARNING")

    if args.show_graph:
        from app.agent.graph import mermaid

        diagram = mermaid()
        (ROOT_DIR / "docs").mkdir(exist_ok=True)
        (ROOT_DIR / "docs" / "graph.md").write_text(f"# Agent graph\n\n```mermaid\n{diagram}\n```\n")
        print(diagram + "\nSaved to docs/graph.md (GitHub renders it as a diagram).")
        return 0

    from app.agent.runner import run_agent

    params = RunParams(count=args.count, niche=args.niche, keywords=args.keywords, categories=args.categories,
                       platforms=args.platforms, days=args.days, max_credits=args.max_credits)
    extra = {}
    if args.demo:
        from app.agent.fakes import FakeBrightData, FakeLLM

        extra = {"bd": FakeBrightData(), "llm": FakeLLM()}
        print("DEMO MODE: fake search results and fake LLM answers.\n")
    else:
        s = get_settings()
        print(f"LLM: {s.llm_provider}/{s.llm_model}   Credit budget: {params.max_credits or s.max_credits_per_run}\n")

    print(f"Finding {params.count} qualified leads (niche: {params.niche or 'any'}, platforms: {', '.join(params.platforms)})")
    try:
        result = await run_agent(params, on_progress=print_progress, **extra)
    except Exception as e:
        print(f"\nRun failed: {e}")
        return 1

    print_leads(result["run_id"])
    print("\n" + "=" * 80)
    print(f"Run {result['run_id']}: {result['qualified']} qualified, {result['low_fit_saved']} low-fit saved, "
          f"{result['skipped']} skipped.  Stop reason: {result['stop_reason']}")
    u = result["usage"]
    print(f"Bright Data: {u['credits_used']}/{u['max_credits']} credits used, {u['cache_hits']} cache hits")
    if result["errors"]:
        print(f"{len(result['errors'])} non-fatal errors (first 5):")
        for err in result["errors"][:5]:
            print(f"  - {err[:160]}")
    if result["export_path"]:
        print(f"Excel: {result['export_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
