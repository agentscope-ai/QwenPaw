# -*- coding: utf-8 -*-
"""Environment loading anchored at the project root."""

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
