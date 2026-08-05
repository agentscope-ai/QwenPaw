# -*- coding: utf-8 -*-
"""Installation-scoped on/off switch for the Computer Use feature."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock

_LOGGER = logging.getLogger(__name__)


def _default_state_path() -> Path:
    from qwenpaw.constant import WORKING_DIR

    return (
        Path(WORKING_DIR)
        / "plugin_runtime"
        / "computer-use"
        / "feature_state.json"
    )


class ComputerUseFeatureState:
    """Persist whether the Computer Use feature is allowed on this host.

    The feature is enabled by default so existing installations keep their
    current behaviour; the user can turn it off from the plugin page. The
    flag is installation-scoped and survives restarts.

    That default applies only when no decision has been recorded. A state file
    that exists but cannot be read is an unknown, not a default, and an unknown
    resolves to off -- the alternative is quietly restoring desktop access that
    the user may have switched off.
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
        except FileNotFoundError:
            # No decision has been recorded yet, so the installation default
            # applies. Nothing is lost by starting from it: the feature being
            # on means an agent may ask, and every action on an application
            # still waits for the user to approve that application.
            return True
        except (OSError, json.JSONDecodeError) as error:
            # A file that exists but cannot be read is different: the user may
            # have turned the feature off, and reading that as on would put a
            # decision about desktop access back the way they did not choose.
            _LOGGER.warning(
                "Computer Use feature state at %s is unreadable (%s); "
                "treating the feature as off until it is set again.",
                self._persistent_path,
                error,
            )
            return False
        enabled = payload.get("enabled")
        if isinstance(enabled, bool):
            return enabled
        # Parsed, but says nothing this code understands -- the same unknown as
        # an unreadable file.
        _LOGGER.warning(
            "Computer Use feature state at %s has no usable 'enabled' flag; "
            "treating the feature as off until it is set again.",
            self._persistent_path,
        )
        return False

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
