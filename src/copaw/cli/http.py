# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

import click
import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8088"


def client(base_url: str) -> httpx.Client:
    """Create HTTP client with /api prefix added to all requests."""
    # Ensure base_url ends with /api
    base = base_url.rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return httpx.Client(base_url=base, timeout=30.0)


def print_json(data: Any) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))
