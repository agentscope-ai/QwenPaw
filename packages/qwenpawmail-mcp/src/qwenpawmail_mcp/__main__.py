# -*- coding: utf-8 -*-
"""Entry point: run the FastMCP server over stdio.

The server starts even without credentials so that ``create_mailbox`` can
be used for registration guidance.  Credential-requiring tools will return
a friendly error when invoked without valid configuration.
"""

from __future__ import annotations

import signal
import sys


def _graceful_shutdown(_signum, _frame):
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    from .server import create_server

    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
