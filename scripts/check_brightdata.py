"""Check that Bright Data search, page fetching and caching work.

    uv run python scripts/check_brightdata.py

Run it twice: the second run should show 0 credits used (everything comes from cache).
"""

import asyncio

from app.services.brightdata import BrightData

QUERY = 'site:reddit.com/r/smallbusiness "automate" "data entry"'
PAGE = "https://example.com"


async def main() -> None:
    async with BrightData(max_credits=5) as bd:
        print(f"1) Google search (past month): {QUERY}")
        results = await bd.search(QUERY, num_results=5)
        for r in results:
            print(f"   - {r['title'][:80]}\n     {r['url']}")
        if not results:
            print("   (no results; try a broader query)")

        print(f"\n2) Fetch page: {PAGE}")
        text = await bd.fetch_page(PAGE)
        print("   " + text[:300].replace("\n", "\n   "))

        print(f"\nUsage: {bd.usage()}")
    print("Bright Data OK")


if __name__ == "__main__":
    asyncio.run(main())
