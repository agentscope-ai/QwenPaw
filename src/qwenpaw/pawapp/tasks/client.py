# -*- coding: utf-8 -*-
"""Scoped SDK: Host owns origins and authenticates scope."""

from .contracts import TaskScope, TaskStoreError


class ScopedTasks:
    def __init__(self, runtime, origins, scope: TaskScope):
        self.runtime, self.origins, self.scope = runtime, origins, scope

    async def dispatch(
        self,
        action_id,
        inputs,
        *,
        request_id,
        app_session_id="default",
        prepare=False,
    ):
        await self.runtime.describe(self.scope, action_id)
        origin = await self.origins.direct(self.scope, app_session_id)
        return await self.runtime.dispatch(
            self.scope,
            action_id,
            inputs=inputs,
            request_id=request_id,
            origin=origin,
            prepare=prepare,
        )

    async def get(self, task_id):
        return (await self.runtime.get(self.scope, task_id)).handle

    async def answer(self, task_id, *, command_id, request_id, answers):
        return await self.runtime.answer(
            self.scope,
            task_id,
            command_id=command_id,
            request_id=request_id,
            answers=answers,
        )

    async def cancel(self, task_id, *, reason=None):
        return await self.runtime.cancel(self.scope, task_id, reason=reason)

    async def open(self, task_id):
        return await self.runtime.open_app(self.scope, task_id)

    async def events(self, task_id, *, after=0, limit=100):
        await self.get(task_id)
        return await self.runtime.store.events(
            self.scope,
            task_id,
            after=after,
            limit=limit,
        )


class ScopedArtifacts:
    def __init__(self, runtime, scope):
        self.runtime, self.scope = runtime, scope

    def _store(self):
        if self.runtime.artifacts is None:
            raise TaskStoreError("artifact_store_unavailable")
        return self.runtime.artifacts

    async def list(self, **filters):
        return await self._store().list(self.scope, **filters)

    async def read(self, artifact_id, version):
        return await self._store().read(self.scope, artifact_id, version)

    async def publish(self, task_id, source, content):
        submission = await self.runtime.get(self.scope, task_id)
        return await self._store().publish(submission, source, content)


class ScopedSetup:
    def __init__(self, runtime, origins, scope):
        self.runtime, self.origins, self.scope = runtime, origins, scope

    def _setup(self):
        if self.runtime.setup is None:
            raise TaskStoreError("setup_runtime_unavailable")
        return self.runtime.setup

    async def request(
        self,
        action_id,
        inputs,
        *,
        idempotency_key,
        app_session_id="default",
        **options,
    ):
        await self.runtime.describe(self.scope, action_id)
        origin = await self.origins.direct(self.scope, app_session_id)
        return await self.runtime.create_setup_request(
            self.scope,
            action_id,
            inputs=inputs,
            origin=origin,
            idempotency_key=idempotency_key,
            presentation="app_entry",
            **options,
        )

    async def get(self, request_id):
        return await self._setup().get(self.scope, request_id)

    async def open(self, request_id):
        return await self._setup().open(self.scope, request_id)

    async def cancel(self, request_id):
        return await self._setup().cancel(self.scope, request_id)

    async def complete(self, result):
        return await self._setup().complete(self.scope, result)
