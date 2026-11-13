# -*- coding: utf-8 -*-
"""Shared upstream quota admission for a single Hub process."""

import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import HTTPException

from ...utils.io_utils import run_sync_io


class SharedLimiter:
    """Aggregate aliases and connections that share upstream quota scopes."""

    def __init__(self, store):
        self.store = store
        self.active = defaultdict(int)
        self.starts = defaultdict(deque)
        self.cooldown_until = 0.0

    def _limits(self, model, connection):
        """Load one configuration snapshot in the caller's worker thread."""
        scope = connection["quota_scope"]
        model_scope = f"{scope}:{model['upstream_model']}"
        # The strictest configured limit wins for a shared supplier quota.
        connections = [connection]
        models = [model]
        with self.store.connect() as db:
            db.execute("BEGIN")
            for row in db.execute(
                "SELECT value_json FROM hub_model_connections",
            ):
                value = json.loads(row[0])
                if value["quota_scope"] == scope:
                    connections.append(value)
            ids = {
                row[0]
                for row in db.execute(
                    "SELECT id FROM hub_model_connections WHERE "
                    "json_extract(value_json, '$.quota_scope') = ?",
                    (scope,),
                )
            }
            for row in db.execute(
                "SELECT value_json FROM hub_managed_models",
            ):
                value = json.loads(row[0])
                if (
                    value["connection_id"] in ids
                    and value["upstream_model"] == model["upstream_model"]
                ):
                    models.append(value)
        return [
            (f"connection:{scope}", connections),
            (f"model:{model_scope}", models),
        ]

    @asynccontextmanager
    async def acquire(self, model, connection):
        """Reject immediately rather than buffering an unbounded queue."""
        limits = await run_sync_io(self._limits, model, connection)
        now = time.monotonic()
        if now < self.cooldown_until:
            raise HTTPException(
                429,
                "Model service recovering",
                headers={"Retry-After": "120"},
            )
        for key, values in limits:
            history = self.starts[key]
            while history and history[0] <= now - 60:
                history.popleft()
            concurrency = min(
                (v["concurrency"] for v in values if v["concurrency"] > 0),
                default=0,
            )
            rpm = min(
                (
                    v["requests_per_minute"]
                    for v in values
                    if v["requests_per_minute"] > 0
                ),
                default=0,
            )
            if (concurrency and self.active[key] >= concurrency) or (
                rpm and len(history) >= rpm
            ):
                raise HTTPException(
                    429,
                    "Organization model is busy",
                    headers={"Retry-After": "60"},
                )
        for key, _ in limits:
            self.active[key] += 1
            self.starts[key].append(now)
        try:
            yield
        finally:
            for key, _ in limits:
                self.active[key] -= 1
