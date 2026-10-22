# -*- coding: utf-8 -*-
"""Versioned, transport-neutral public models for PawApp authors.

The Python adapter is the execution transport. These JSON schemas describe
data exchanged with the Host; they do not grant authority or execute code.
"""

from ..tasks.contracts import (
    ApprovalRequest,
    ApprovalChoice,
    ApprovalCost,
    ApprovalReceipt,
    ApprovalDecision,
    ActionDescriptor,
    ArtifactCollection,
    ArtifactRef,
    ExecutorEvent,
    ProjectRef,
    TaskAnswer,
    TaskCommand,
    TaskHandle,
    TaskInputRequest,
    TaskExperienceDefinition,
    TaskExperienceUpdate,
    TaskScope,
    TaskSubmission,
    TaskEvent,
)
from ..setup.contracts import SetupRequest, SetupResult, SetupOpenAction
from ..handoffs import OpenAppAction

VERSION = 1
MODELS = (
    ApprovalRequest,
    ApprovalChoice,
    ApprovalCost,
    ApprovalReceipt,
    ApprovalDecision,
    ActionDescriptor,
    ArtifactCollection,
    ArtifactRef,
    ExecutorEvent,
    ProjectRef,
    TaskAnswer,
    TaskCommand,
    TaskHandle,
    TaskInputRequest,
    TaskExperienceDefinition,
    TaskExperienceUpdate,
    TaskScope,
    TaskSubmission,
    TaskEvent,
    SetupRequest,
    SetupResult,
    SetupOpenAction,
    OpenAppAction,
)


def schema_bundle():
    definitions = {}
    for model in MODELS:
        schema = model.model_json_schema()
        definitions.update(schema.pop("$defs", {}))
        definitions[model.__name__] = schema
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:qwenpaw:pawapp:contracts:1",
        "$defs": definitions,
    }


__all__ = [model.__name__ for model in MODELS] + ["VERSION", "schema_bundle"]
