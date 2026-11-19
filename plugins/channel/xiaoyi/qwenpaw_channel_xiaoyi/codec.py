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


def new_artifact_id():
    return f"artifact_{uuid.uuid4().hex[:16]}"


def build_artifact_msg(
    agent_id,
    route,
    parts,
    *,
    artifact_id=None,
    append=True,
    last_chunk=True,
    final=False,
):
    return _envelope(
        agent_id,
        route,
        {
            "taskId": _native_id(route, "task_id"),
            "kind": "artifact-update",
            f"append": append,
            f"lastChunk": last_chunk,
            "final": final,
            "artifact": {
                f"artifactId": artifact_id or new_artifact_id(),
                "parts": parts,
            },
        },
    )


def build_status_msg(agent_id, route, state, text=f""):
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
                    f"parts": [{f"kind": f"text", f"text": text}],
                },
                f"state": state,
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
