"""Installation-scoped on/off switch for the Computer Use feature."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock


def _default_state_path() -> Path:
    from qwenpaw.constant import WORKING_DIR

    return (
        Path(WORKING_DIR)
        / "plugin_runtime"
        / "computer-use-tool"
        / "feature_state.json"
    )


class ComputerUseFeatureState:
    """Persist whether the Computer Use feature is allowed on this host.

    The feature is enabled by default so existing installations keep their
    current behaviour; the user can turn it off from the plugin page. The
    flag is installation-scoped and survives restarts.
    """

    def __init__(self, persistent_path: Path | None = None) -> None:
        self._lock = RLock()
        self._persistent_path = persistent_path or _default_state_path()
        self._enabled = self._load()

    def is_enabled(self) -> bool:
        """Return whether desktop automation is currently allowed."""
        with self._lock:
            return self._enabled

    def set_enabled(self, value: bool) -> None:
        """Persist a new enabled/disabled decision for this installation."""
        with self._lock:
            self._enabled = bool(value)
            self._save_locked()

    def _load(self) -> bool:
        try:
            with self._persistent_path.open(encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError):
            return True
        enabled = payload.get("enabled", True)
        return bool(enabled)

    def _save_locked(self) -> None:
        self._persistent_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._persistent_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps({"enabled": self._enabled}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary_path, self._persistent_path)


_feature_state: ComputerUseFeatureState | None = None


def get_computer_use_feature_state() -> ComputerUseFeatureState:
    """Return the process-wide Computer Use feature switch."""
    global _feature_state
    if _feature_state is None:
        _feature_state = ComputerUseFeatureState()
    return _feature_state
