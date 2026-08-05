#!/usr/bin/env python3
"""Stage and verify the Playwright Chromium revision for Tauri packages."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and smoke-test Playwright Chromium for Tauri",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Playwright browser cache directory to stage",
    )
    return parser.parse_args()


async def _smoke_test() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto("data:text/html,<title>qwenpaw-browser-smoke</title>")
            title = await page.title()
            if title != "qwenpaw-browser-smoke":
                raise RuntimeError(f"unexpected Playwright smoke-test title: {title}")
        finally:
            await browser.close()


def main() -> None:
    args = _parse_args()
    dest = args.dest.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(dest)

    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    if not any(path.is_dir() for path in dest.glob("chromium-*")):
        raise RuntimeError(f"Playwright Chromium was not staged at {dest}")
    asyncio.run(_smoke_test())
    print(f"Staged and verified Playwright Chromium at {dest}")


if __name__ == "__main__":
    main()
