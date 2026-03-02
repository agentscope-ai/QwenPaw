# -*- coding: utf-8 -*-
"""macOS .app entry: run CoPaw server (copaw app). Used as PyInstaller entry."""
from __future__ import annotations


def main() -> None:
    from copaw.cli.app_cmd import app_cmd

    app_cmd.main(args=["--host", "0.0.0.0"])


if __name__ == "__main__":
    main()
