# -*- coding: utf-8 -*-
"""Own one gateway attempt from durable admission through final cleanup."""

import asyncio
import logging
from contextlib import AsyncExitStack

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ...utils.io_utils import run_async_to_completion, run_sync_io
from .budget import BudgetExceededError
from .protocol import validate_request

logger = logging.getLogger(__name__)


class GatewayRequest:
    """Keep reservation ownership even when its caller is cancelled."""

    def __init__(self, budgets, catalog):
        self.budgets = budgets
        self.catalog = catalog
        self.stack = AsyncExitStack()
        self.reservation = None
        self._closing = None

    @property
    def request_id(self):
        """Return the durable identity after successful admission."""
        return self.reservation[0] if self.reservation else None

    async def reserve(self, identity, body):
        """Finish and retain admission before delivering cancellation."""
        limit = validate_request(body)
        with anyio.CancelScope(shield=True):
            await run_async_to_completion(
                self._reserve(identity, body["model"], limit),
            )
        # Deliver an enclosing AnyIO cancellation before dispatching anything.
        await anyio.lowlevel.checkpoint()
        return self.reservation

    async def _reserve(self, identity, model_id, limit):
        try:
            self.reservation = await run_sync_io(
                self.budgets.reserve,
                identity,
                model_id,
                self.catalog,
                limit,
            )
        except BudgetExceededError as exc:
            raise HTTPException(403, "hub_budget_exceeded") from exc
        except PermissionError as exc:
            raise HTTPException(403, "hub_model_unavailable") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    async def dispatch(self):
        """Persist dispatch before the transport can send upstream bytes."""
        with anyio.CancelScope(shield=True):
            await run_sync_io(self.budgets.dispatch, self.request_id)
        await anyio.lowlevel.checkpoint()

    async def close(self, actual=None, error=None):
        """Drain settlement and resource cleanup under either cancel model."""
        with anyio.CancelScope(shield=True):
            if self._closing is None:
                self._closing = asyncio.create_task(self._close(actual, error))
            await run_async_to_completion(self._closing)

    async def _close(self, actual, error):
        try:
            if self.request_id is not None:
                await run_sync_io(
                    self.budgets.settle,
                    self.request_id,
                    actual,
                    error,
                )
        except Exception:
            # Keep the ledger pending for recovery; never log request content.
            logger.exception(f"Model settlement failed: {self.request_id}")
            raise
        finally:
            await self.stack.aclose()


class GatewayStreamingResponse(StreamingResponse):
    """Retain request ownership even if sending headers or a chunk fails."""

    def __init__(self, content, attempt, **kwargs):
        super().__init__(content, **kwargs)
        self.attempt = attempt

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.attempt.close(error="stream_incomplete")
