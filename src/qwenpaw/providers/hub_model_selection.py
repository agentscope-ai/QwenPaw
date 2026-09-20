# -*- coding: utf-8 -*-
"""Personal selector membership, independent of organization model grants."""

import json
from pathlib import Path

from ..utils.io_utils import get_sync_path_lock, write_json_atomic


def read_selection(path: Path) -> dict:
    """Read only personal UI preferences, never upstream credentials."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding=f"utf-8"))


def update_selection(
    path: Path, model_id: str, *, selected=None, seen=False, hidden=None
) -> dict:
    """Atomically merge selection changes across concurrent requests."""
    with get_sync_path_lock(path):
        state = read_selection(path)
        for field, enabled in ((f"selected", selected), (f"hidden", hidden)):
            if enabled is None:
                continue
            ids = set(state.get(field, []))
            if enabled:
                ids.add(model_id)
            else:
                ids.discard(model_id)
            state[field] = sorted(ids)
        if seen:
            state[f"seen"] = sorted(set(state.get(f"seen", [])) | {model_id})
        write_json_atomic(path, state)
        return state


def replace_selection(path: Path, model_ids: list[str]) -> dict:
    """Replace personal membership while preserving other preferences."""
    with get_sync_path_lock(path):
        state = read_selection(path)
        state[f"selected"] = sorted(set(model_ids))
        write_json_atomic(path, state)
        return state


def apply_selection(provider, state: dict, active=None):
    """Intersect personal choices with the currently authorized catalog."""
    selected = set(state.get(f"selected", []))
    if active is not None and active.provider_id == provider.id:
        selected.add(active.model)
    for model in provider.models:
        model.source = f"user" if model.id in selected else f"builtin"
    provider.seen_model_ids = list(state.get(f"seen", []))
    provider.hidden_model_ids = list(state.get(f"hidden", []))
    return provider
