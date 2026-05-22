# -*- coding: utf-8 -*-
"""Artifact model: session-level file-artifact index entry.

On every ``finish_subtask`` that records files, RuntimeStateManager
projects each ``NodeOutput.files`` ``FileRef`` into an ``ArtifactItem``
appended to the session ``artifacts`` list, which then backs the
``GET /files`` / preview / download endpoints.
"""

from pydantic import BaseModel, Field

from agentscope._utils._common import _get_timestamp


class ArtifactItem(BaseModel):
    """Session-level file-artifact index entry (append-only)."""

    graph_id: str = Field(description="Owning graph id.")
    node_id: str = Field(description="Owning node id.")
    name: str = Field(description="File name, e.g. ``dau_trend.png``.")
    path: str = Field(
        description="Sandbox-view relative path; same as ``FileRef.path``."
    )
    mime_type: str = Field(description="MIME type, e.g. ``image/png``.")
    size_bytes: int = Field(
        default=0,
        description="File size in bytes, filled in via ``stat`` on the backend.",
    )
    created_at: str = Field(
        default_factory=_get_timestamp,
        description="Creation timestamp.",
    )
