# -*- coding: utf-8 -*-
"""Allow running QwenPaw via ``python -m qwenpaw``."""
from .cli.main import cli

if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
