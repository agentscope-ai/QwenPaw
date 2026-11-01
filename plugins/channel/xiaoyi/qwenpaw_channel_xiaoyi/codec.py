# -*- coding: utf-8 -*-
"""Native A2A envelopes, independent of host Agent/rendering objects."""

import json
import uuid


def _native_id(route, name):
    encoded = route.get(name + "_json")
    return json.loads(encoded) if encoded is not None else route[name]


def _envelope(agent_id, route, result):
    return {
        "msgType": "agent_response",
        "agentId": agent_id,
        "sessionId": route["session_id"],
        "taskId": _native_id(route, "task_id"),
        "msgDetail": json.dumps(
            {
                "jsonrpc": "2.0",
                "id": _native_id(route, "message_id"),
                "result": result,
            },
        ),
    }


def build_artifact_msg(agent_id, route, parts, *, final=False):
    return _envelope(
        agent_id,
        route,
        {
            "taskId": _native_id(route, "task_id"),
            "kind": "artifact-update",
            "append": True,
            "lastChunk": True,
            "final": final,
            "artifact": {
                "artifactId": "artifact_" + uuid.uuid4().hex[:16],
                "parts": parts,
            },
        },
    )


def build_completed_msg(agent_id, route):
    return _envelope(
        agent_id,
        route,
        {
            "taskId": _native_id(route, "task_id"),
            "kind": "status-update",
            "final": False,
            "status": {
                "message": {
                    "role": "agent",
                    "parts": [{"kind": "text", "text": ""}],
                },
                "state": "completed",
            },
        },
    )


def build_control_response(agent_id, request_id, session_id, state):
    result = {"status": {"state": state}}
    if state == "canceled":
        result["id"] = request_id
    return _envelope(
        agent_id,
        {
            "session_id": session_id,
            "task_id": request_id,
            "message_id": request_id,
        },
        result,
    )
