# -*- coding: utf-8 -*-
"""ID and timestamp helpers; IDs never carry legacy aliases."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def new_id(prefix: str) -> str:
    clean = prefix.strip().lower().replace("_", "-")
    return f"{clean}-{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()
