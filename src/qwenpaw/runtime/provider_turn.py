# -*- coding: utf-8 -*-
"""Provider connections and streams owned by an Agent turn."""

import asyncio
from contextlib import ExitStack, contextmanager

from ..plugins.errors import StaleContextError
from .turn_context import current_provider_turn


class ProviderTurn:
    """Retain plugin admission and suspended streams for one Agent turn."""

    def __init__(self):
        self.task = asyncio.current_task()
        self._admissions = ExitStack()
        self._contexts = set()
        self.producers = set()
        self.closed = False

    @contextmanager
    def bind(self):
        """Expose this turn for one step of runtime execution."""
        token = current_provider_turn.set(self)
        try:
            yield
        finally:
            current_provider_turn.reset(token)

    def guard(self):
        if self.closed:
            raise StaleContextError("The owning Agent turn has ended")

    def retain(self, provider_context, admission):
        self.guard()
        if provider_context not in self._contexts:
            self._admissions.enter_context(admission)
            self._contexts.add(provider_context)

    async def close(self):
        self.closed = True
        if self.producers or self._contexts:
            from ..utils.io_utils import run_async_to_completion

            await run_async_to_completion(self._close_resources())

    async def _close_resources(self):
        from ..plugins.custody import stop_task

        try:
            results = await asyncio.gather(
                *(
                    stop_task(task, "provider-inference")
                    for task in self.producers
                ),
                return_exceptions=True,
            )
        finally:
            self._admissions.close()
            self._contexts.clear()
        for result in results:
            if isinstance(result, BaseException):
                raise result
