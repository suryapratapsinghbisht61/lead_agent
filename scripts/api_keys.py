"""Manage API keys for the FastAPI server.

    uv run python scripts/api_keys.py create "my laptop"    # prints the key ONCE, save it
    uv run python scripts/api_keys.py list
    uv run python scripts/api_keys.py revoke 3
"""

import argparse
import sys

from app.db import repo
from app.db.session import init_db


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("name")
    sub.add_parser("list")
    sub.add_parser("revoke").add_argument("id", type=int)
    args = p.parse_args()
    init_db()

    if args.cmd == "create":
        key = repo.create_api_key(args.name)
        print(f"API key for '{args.name}' (shown only once, store it safely):\n\n  {key}\n")
        print("Use it as a header:  X-API-Key: <key>")
    elif args.cmd == "list":
        for k in repo.list_api_keys():
            print(f"{k.id:>3}  {'active ' if k.active else 'revoked'}  {k.created_at:%Y-%m-%d}  {k.name}")
    elif args.cmd == "revoke":
        print("Revoked" if repo.revoke_api_key(args.id) else "Not found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
