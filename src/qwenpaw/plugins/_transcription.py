# -*- coding: utf-8 -*-
"""Lifecycle-owned bridge for transcription callbacks."""

# Host adapters access ownership behind the public SDK.
# pylint: disable=protected-access

import asyncio
import re
from dataclasses import fields

from .errors import SDKError, StaleContextError
from .resources import Registration
from .transcription import (
    TranscriptionContext,
    TranscriptionResult,
    TranscriptionSpec,
    TranscriptionStatus,
)


class TranscriptionBackend:
    def __init__(self, context, spec):
        self.context = context
        self.spec = spec
        self.plugin_id = context.plugin_id
        self.closed = False

    async def call(self, *, file_path=None, workspace_id="", session_id=""):
        if self.closed:
            raise StaleContextError("Transcription backend was released")
        deadline = (
            None
            if self.spec.timeout is None
            else asyncio.get_running_loop().time() + self.spec.timeout
        )
        async with (
            asyncio.timeout_at(deadline),
            self.context._invocation(
                workspace_id=workspace_id,
                session_id=session_id,
                deadline=deadline,
            ) as base,
        ):
            public = TranscriptionContext(
                **{
                    field.name: getattr(base, field.name)
                    for field in fields(base)
                },
                backend_id=self.spec.id,
            )
            status = file_path is None
            result = await self.context._call(
                self.spec.status if status else self.spec.transcribe,
                public,
                *(() if status else (file_path,)),
            )
            expected = TranscriptionStatus if status else TranscriptionResult
            if not isinstance(result, expected):
                raise SDKError(
                    f"Transcription callback must return {expected.__name__}",
                )
            return result


def register(context, spec):
    if not isinstance(spec, TranscriptionSpec):
        raise SDKError("Expected a TranscriptionSpec")
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", spec.id)
        or spec.id in {"disabled", "whisper_api"}
        or not callable(spec.transcribe)
        or not callable(spec.status)
    ):
        raise SDKError("Invalid transcription backend specification")
    if spec.timeout is not None and spec.timeout <= 0:
        raise SDKError("Transcription timeout must be positive")
    context._guard()
    adapter = TranscriptionBackend(context, spec)
    registry = context._api._registry
    registry.register_transcription_backend(spec.id, adapter)

    def release():
        adapter.closed = True
        registry.drop_transcription_backend(spec.id, adapter)

    context._api._note_runtime(f"transcription:{spec.id}", release)
    return Registration(
        release,
        owner=context.resources.owner,
        description=f"transcription:{spec.id}",
    )
