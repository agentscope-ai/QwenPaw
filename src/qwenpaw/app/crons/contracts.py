# -*- coding: utf-8 -*-
"""Backend-neutral declarations for service-contributed cron jobs."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceCronJob:
    """A cron job declared by a workspace service.

    The declaration intentionally contains no APScheduler types. Services own
    job semantics and configuration; :class:`CronManager` owns scheduling.
    """

    key: str
    cron: str
    callback: Callable[[], Awaitable[None]]
    misfire_grace_seconds: int = 600
    jitter_seconds: int = 0
