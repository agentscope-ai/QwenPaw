#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start the configured context service and verify the private gateway."""
# pylint: disable=wrong-import-position,protected-access

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = APP_DIR.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(APP_DIR))

from backend import main  # noqa: E402


async def check() -> None:
    await main._context_service.start()  # noqa: SLF001
    try:
        await main._gateway.start()  # noqa: SLF001
        try:
            health = await main._gateway.json(
                "GET",
                "/api/health",
            )  # noqa: SLF001
            print(json.dumps(health, ensure_ascii=False, indent=2))
        finally:
            await main._gateway.stop()  # noqa: SLF001
    finally:
        await main._context_service.stop()  # noqa: SLF001


if __name__ == "__main__":
    asyncio.run(check())
