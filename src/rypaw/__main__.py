# -*- coding: utf-8 -*-
"""Allow running CoPaw via ``python -m copaw``."""
from .cli.main import cli

if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
