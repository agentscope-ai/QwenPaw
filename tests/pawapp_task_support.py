# -*- coding: utf-8 -*-
"""App-independent descriptors for Host task conformance tests."""

from qwenpaw.pawapp.tasks import ActionDescriptor


def analysis_action_descriptor() -> ActionDescriptor:
    """Exercise scoped resources without importing an installed App adapter."""
    return ActionDescriptor(
        app_id="example-analysis",
        action_id="analyze",
        summary="Analyze an authorized test datasource.",
        engagements=("delegated", "direct"),
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "datasource_id": {"type": "string", "minLength": 1},
            },
            "required": ["text", "datasource_id"],
            "additionalProperties": False,
        },
        output_types=("text/plain", "qwenpaw:file"),
        permissions=("data.analysis.execute", "data.datasource.read"),
        effects=("model_usage", "datasource_query"),
        adapter_ref="fixture.analysis.v1",
    )
