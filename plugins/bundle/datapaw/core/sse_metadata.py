# -*- coding: utf-8 -*-
"""Shared metadata key schema for DAG-node-routed SSE messages.

The agent layer writes these keys on outbound ``Msg`` so the frontend
can route streaming tokens to the originating DAG node. The channel
layer reads them when extracting metadata from ``message`` frames and
injecting it into the same-``msg_id`` ``content`` frames (content
frames don't carry their own metadata at the SSE wire level).

Keep the agent writer and the channel reader aligned through this
single source — adding a new routing key requires touching only the
tuple below; the writer and reader iterate over it.
"""
from __future__ import annotations


NODE_ROUTING_METADATA_KEYS: tuple[str, ...] = (
    "graph_id",
    "node_id",
    "subagent_event",
    "subagent_tool_name",
)

SUBAGENT_ROUTING_BLOCK_TYPE = "_r"
