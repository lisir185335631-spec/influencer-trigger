"""Interactive YouTube cookie importer.

Usage (from server/ directory):
    .venv/Scripts/python scripts/import_youtube_cookies.py

Opens a real Chromium window. You log into YouTube manually (recommended:
small/burner account, not your main one). Press Enter in the terminal when
done. The script saves the storage_state to server/data/youtube-cookies.json
which the scraper auto-loads on next run.

Note: cookies expire every 30-60 days. Re-run this script when scraper logs
start showing 'no cookies.json' or 'View email button=0' for every channel.
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright


COOKIE_PATH = Path(__file__).resolve().parent.parent / "data" / "youtube-cookies.json"


async def main() -> int:
    print("=" * 60)
    print(" YouTube Cookie Importer")
    print("=" * 60)
    print(f"Output file: {COOKIE_PATH}")
    print()
    print("Step 1: a Chromium window will open shortly.")
    print("Step 2: log into YouTube with a SMALL / BURNER account.")
    print("        (Main account = higher ban risk.)")
    print("Step 3: once you see your YouTube home page (signed in),")
    print("        come back to this terminal and press Enter.")
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await ctx.new_page()
        await page.goto("https://accounts.google.com/signin")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, input, "Press Enter AFTER you finished logging into YouTube... "
        )

        state = await ctx.storage_state()
        cookie_count = len(state.get("cookies", []))
        if cookie_count == 0:
            print("ERROR: no cookies were captured. Did you complete the login?")
            await browser.close()
            return 1

        COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(f"OK: saved {cookie_count} cookies to {COOKIE_PATH}")
        print()
        print("Next: restart uvicorn so the scraper picks up the cookies.")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
