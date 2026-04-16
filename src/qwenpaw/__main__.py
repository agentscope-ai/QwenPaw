# -*- coding: utf-8 -*-
"""Allow running QwenPaw via ``python -m qwenpaw``."""

import asyncio
from .cli.main import cli

if "_patch_asyncio" in asyncio.run.__qualname__:
    print(
        "\nFIX: loop_factory exception of asyncio.run in PyCharm Debug Mode\n",
    )
    import asyncio.runners

    asyncio.run = asyncio.runners.run

if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
