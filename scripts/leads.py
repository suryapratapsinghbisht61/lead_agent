"""Look at and manage saved leads from the terminal.

    uv run python scripts/leads.py list                    # qualified leads, newest first
    uv run python scripts/leads.py list --all --min-score 7 --category startup
    uv run python scripts/leads.py show 12                 # full details + message
    uv run python scripts/leads.py status 12 sent          # new | sent | replied | meeting | closed
    uv run python scripts/leads.py note 12 "Replied on LinkedIn, call Friday"
    uv run python scripts/leads.py runs                    # run history
    uv run python scripts/leads.py export                  # all qualified leads -> exports/all_leads.xlsx
"""

import argparse
import sys

from app.core.config import get_settings
from app.db import repo
from app.db.models import OUTREACH_STATUSES
from app.db.session import init_db
from app.services.export import leads_to_xlsx


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--all", action="store_true", help="include low-fit leads")
    ls.add_argument("--min-score", type=int)
    ls.add_argument("--category", nargs="*")
    ls.add_argument("--platform", nargs="*")
    ls.add_argument("--status", nargs="*")
    ls.add_argument("--run")
    sub.add_parser("show").add_argument("id", type=int)
    st = sub.add_parser("status")
    st.add_argument("id", type=int)
    st.add_argument("status", choices=OUTREACH_STATUSES)
    nt = sub.add_parser("note")
    nt.add_argument("id", type=int)
    nt.add_argument("text")
    sub.add_parser("runs")
    sub.add_parser("export")
    args = p.parse_args()
    init_db()

    if args.cmd == "list":
        leads, total = repo.list_leads(run_id=args.run, categories=args.category, platforms=args.platform,
                                       statuses=args.status, min_score=args.min_score, include_low_fit=args.all,
                                       limit=500)
        print(f"{'ID':>4}  {'Fit':>3}  {'Category':10} {'Platform':8} {'Status':8} Name")
        for lead in leads:
            print(f"{lead.id:>4}  {lead.fit_score:>3}  {lead.category or '-':10} {lead.platform:8} {lead.status:8} "
                  f"{lead.name}" + (f" @ {lead.company}" if lead.company else ""))
        print(f"\n{total} leads")
    elif args.cmd == "show":
        lead = repo.get_lead(args.id)
        if not lead:
            print("Not found")
            return 1
        for field, value in lead.model_dump().items():
            print(f"{field:16} {value}")
    elif args.cmd == "status":
        print("Updated" if repo.update_lead(args.id, status=args.status) else "Not found")
    elif args.cmd == "note":
        print("Updated" if repo.update_lead(args.id, notes=args.text) else "Not found")
    elif args.cmd == "runs":
        print(f"{'Run ID':12}  {'Status':9} {'Qual':>4} {'Credits':>7}  Created           Stop reason")
        for r in repo.list_runs():
            print(f"{r.id:12}  {r.status:9} {r.qualified_count:>4} {r.credits_used:>7}  "
                  f"{r.created_at:%Y-%m-%d %H:%M}  {r.stop_reason or r.progress}")
    elif args.cmd == "export":
        leads, _ = repo.list_leads(limit=100_000)
        path = get_settings().export_dir / "all_leads.xlsx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(leads_to_xlsx(leads))
        print(f"{len(leads)} leads -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
