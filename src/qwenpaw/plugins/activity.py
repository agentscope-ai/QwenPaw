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

    @contextmanager
    def invocation(self):
        task = asyncio.current_task()
        if self.blocked:
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

    @asynccontextmanager
    async def mutation(self, *, interrupt_tasks=False):
        current = asyncio.current_task()
        if self.mutator is current:
            yield
            return
        pending = {task for task in self.tasks if not task.done()}
        if current in pending:
            raise PluginBusyError(
                self.plugin_id,
                len(pending),
                can_interrupt=False,
            )
        if pending and not interrupt_tasks:
            raise PluginBusyError(
                self.plugin_id,
                len(pending),
                can_interrupt=not self.blocked,
            )
        self.blocked = True
        self.mutator = current
        try:
            if pending:
                for task in pending:
                    if not task.cancelling():
                        task.cancel()
                _, pending = await asyncio.wait(
                    pending,
                    timeout=INTERRUPT_TIMEOUT_SECONDS,
                )
                if pending:
                    raise PluginBusyError(
                        self.plugin_id,
                        len(pending),
                        can_interrupt=False,
                    )
            yield
        finally:
            self.mutator = None
            # A timed-out/cancelled cleanup must not admit new work.
            self.blocked = any(not task.done() for task in self.tasks)


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
