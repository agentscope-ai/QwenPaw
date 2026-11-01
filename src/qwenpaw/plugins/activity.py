# -*- coding: utf-8 -*-
"""Admission and bounded interruption for plugin command invocations."""

import asyncio
from contextlib import asynccontextmanager, contextmanager

INTERRUPT_TIMEOUT_SECONDS = 5.0


class PluginBusyError(RuntimeError):
    """A lifecycle operation cannot replace resources used by a command."""

    def __init__(self, plugin_id, count, *, can_interrupt=True):
        message = (
            "插件正在执行任务" if can_interrupt else "插件任务尚未停止，请稍后重试；若持续无法停止，请重启后再操作"
        )
        super().__init__(message)
        self.detail = {
            "code": "plugin_busy",
            "plugin_id": plugin_id,
            "message": message,
            "active_tasks": count,
            "can_interrupt": can_interrupt,
            "quiescent": False,
            "needs_restart": not can_interrupt,
        }


class PluginActivity:
    """Keep active requests alive across replacement of plugin instances."""

    def __init__(self, plugin_id):
        self.plugin_id = plugin_id
        self.tasks = {}
        self.blocked = False
        self.mutator = None
        self.cleanup_tasks = set()
        self.cleanup_retries = {}
        self._interrupted_tasks = set()

    @contextmanager
    def invocation(self, *, cleanup=False):
        task = asyncio.current_task()
        if self.blocked and not (cleanup and task in self.cleanup_tasks):
            raise PluginBusyError(
                self.plugin_id,
                len(self.tasks),
                can_interrupt=False,
            )
        self.tasks[task] = self.tasks.get(task, 0) + 1
        try:
            yield
        finally:
            self.tasks[task] -= 1
            if not self.tasks[task]:
                del self.tasks[task]

    def retain_cleanup(self, task):
        """Reserve only an already-admitted SDK request's terminal callback."""
        self.cleanup_tasks.add(task)
        task.add_done_callback(self.cleanup_tasks.discard)

    async def retry_cleanup(self):
        """Wait for lifecycle retry without cancelling live work."""
        task = asyncio.current_task()
        retry = asyncio.Event()
        self.cleanup_retries[task] = retry
        try:
            await retry.wait()
        except asyncio.CancelledError:
            return True
        finally:
            self.cleanup_retries.pop(task, None)
        return False

    def _pending(self):
        return {
            task
            for task in self.tasks.keys() | self.cleanup_tasks
            if not task.done()
        }

    @asynccontextmanager
    async def mutation(self, *, interrupt_tasks=False):
        current = asyncio.current_task()
        if self.mutator is current:
            yield
            return
        pending = self._pending()
        if current in pending:
            raise PluginBusyError(
                self.plugin_id,
                len(pending),
                can_interrupt=False,
            )
        drainable = pending <= (
            self.cleanup_retries.keys()
            | self.cleanup_tasks
            | self._interrupted_tasks
        )
        if pending and not interrupt_tasks and not drainable:
            raise PluginBusyError(
                self.plugin_id,
                len(pending),
                can_interrupt=not self.blocked,
            )
        self.blocked = True
        self.mutator = current
        try:
            if pending:
                deadline = (
                    asyncio.get_running_loop().time()
                    + INTERRUPT_TIMEOUT_SECONDS
                )
                for task in pending:
                    interrupt = (
                        interrupt_tasks
                        and task not in self.cleanup_tasks
                        and task not in self._interrupted_tasks
                    )
                    if interrupt:
                        # Retain retry eligibility even if this mutation is
                        # cancelled before the request actually exits.
                        self._interrupted_tasks.add(task)
                        task.add_done_callback(self._interrupted_tasks.discard)
                    retry = self.cleanup_retries.get(task)
                    if retry is not None:
                        retry.set()
                    elif interrupt and not task.cancelling():
                        task.cancel()
                # A cancelled request may enqueue its terminal callback while
                # draining. Keep the gate closed until those new owners finish.
                while pending:
                    _, remaining = await asyncio.wait(
                        pending,
                        timeout=max(
                            0,
                            deadline - asyncio.get_running_loop().time(),
                        ),
                    )
                    pending = remaining | self._pending()
                    if (
                        pending
                        and asyncio.get_running_loop().time() >= deadline
                    ):
                        raise PluginBusyError(
                            self.plugin_id,
                            len(pending),
                            can_interrupt=False,
                        )
            yield
        finally:
            self.mutator = None
            # A timed-out/cancelled cleanup must not admit new work.
            self.blocked = bool(self._pending())


@contextmanager
def plugin_invocation(plugin_id):
    """Track managed commands; leave core and standalone registries alone."""
    from .lifecycle import _LIVE_INSTANCES

    instance = _LIVE_INSTANCES.get(plugin_id)
    if instance is None:
        yield
    else:
        with instance.activity.invocation():
            if instance.delegate is not None and not instance.activated:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' is not active; "
                    "commands are unavailable until activation completes",
                )
            yield
