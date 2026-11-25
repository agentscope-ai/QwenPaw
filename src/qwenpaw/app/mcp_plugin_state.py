# -*- coding: utf-8 -*-
"""One-shot migration decisions, independent of plugin runtime health."""

import json
import re
from uuid import uuid4

from ..plugins.install_lock import plugin_install_lock
from ..utils.io_utils import write_json_atomic

MARKER = ".mcp-plugin-migration.json"


def automatic(marker):
    if marker is None:
        return None
    return marker["automatic"]


def read_marker(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict) or type(value.get("schema")) is not int:
        raise ValueError("Invalid MCP upgrade record")
    if value["schema"] != 2 or not isinstance(value.get("workspaces"), dict):
        raise ValueError("Invalid MCP upgrade record")
    if any(
        not isinstance(key, str)
        or status not in ("unused", "configured", "needs_review")
        for key, status in value["workspaces"].items()
    ):
        raise ValueError("Invalid MCP workspace record")
    if (
        not isinstance(value.get("automatic"), str)
        or value["automatic"]
        not in {"not_required", "attempted", "completed", "needs_review"}
        or not isinstance(value.get("revision"), str)
        or re.fullmatch(r"[a-f0-9]{32}", value["revision"]) is None
        or not isinstance(value.get("diagnostics", []), list)
        or not all(
            isinstance(code, str) for code in value.get("diagnostics", [])
        )
    ):
        raise ValueError("Invalid MCP automatic decision")
    fields = {"transaction", "digest", "stage"}
    if fields.intersection(value):
        if (
            not fields <= value.keys()
            or not isinstance(value["transaction"], str)
            or re.fullmatch(r"[a-f0-9]{32}", value["transaction"]) is None
            or not isinstance(value["digest"], str)
            or re.fullmatch(r"[a-f0-9]{64}", value["digest"]) is None
            or not isinstance(value["stage"], str)
            or value["stage"]
            not in {"preparing", "files_committed", "completed"}
        ):
            raise ValueError("Invalid MCP installation transaction")
    return value


def publish_marker(path, previous, *, recover_invalid=False, **updates):
    """Claim/update only the revision observed by this operation.

    Hold no OS lock while awaiting plugin or dependency lifecycle work.
    The caller settles this complete transaction with run_sync_io.
    """
    with plugin_install_lock(path.with_suffix(".lock"), timeout=5):
        try:
            current = read_marker(path)
        except ValueError:
            if not recover_invalid:
                raise
            current = None
        if current != previous:
            raise RuntimeError("MCP migration decision changed")
        value = {
            **(previous or {}),
            "schema": 2,
            "automatic": automatic(previous) or "not_required",
            "workspaces": (previous or {}).get("workspaces", {}),
            "diagnostics": (previous or {}).get("diagnostics", []),
            **updates,
            "revision": uuid4().hex,
        }
        write_json_atomic(path, value)
        return value
