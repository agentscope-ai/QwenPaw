# -*- coding: utf-8 -*-
# pylint:disable=unused-import
"""
PyInstaller runtime hook: fix opentelemetry in frozen apps.

- entry_points("opentelemetry_context") empty -> fake contextvars entry.
- entry_points("opentelemetry_resource_detector", name="otel") empty ->
  fake OTELResourceDetector entry so Resource.create() next(iter(...))
  does not raise StopIteration.
- version() for missing dist-info (opentelemetry-*, email-validator, etc.)
  patched in importlib_metadata and importlib.metadata to return "1.0.0".
"""
from __future__ import annotations

import sys


def _make_version_patch(orig_version, not_found_exc):
    def _patched(name: str) -> str:
        try:
            return orig_version(name)
        except not_found_exc:
            return "1.0.0"

    return _patched


# Patch package importlib_metadata (used by opentelemetry).
try:
    import importlib_metadata as _meta

    _meta.version = _make_version_patch(
        _meta.version,
        getattr(_meta, "PackageNotFoundError", Exception),
    )
except Exception:
    pass

# Patch stdlib importlib.metadata (used by pydantic/fastapi).
try:
    import importlib.metadata as _stdlib_meta

    _stdlib_meta.version = _make_version_patch(
        _stdlib_meta.version,
        getattr(_stdlib_meta, "PackageNotFoundError", Exception),
    )
except Exception:
    pass


def _install_patch() -> None:
    try:
        import opentelemetry.util._importlib_metadata as _otel_meta
    except ImportError as _e:
        sys.stderr.write(
            "CoPaw runtime hook: opentelemetry.util not found, "
            "context may raise StopIteration in frozen app.\n",
        )
        return
    _orig = _otel_meta.entry_points

    class _FakeContextEntry:
        def load(self):
            def _factory():
                from opentelemetry.context.contextvars_context import (
                    ContextVarsRuntimeContext,
                )

                return ContextVarsRuntimeContext()

            return _factory

    class _FakeOtelDetectorEntry:
        """Fake entry for opentelemetry_resource_detector 'otel' in frozen app."""

        def load(self):
            from opentelemetry.sdk.resources import OTELResourceDetector

            return OTELResourceDetector

    def _patched_entry_points(**params):
        out = _orig(**params)
        group = params.get("group")
        name = params.get("name")
        if group == "opentelemetry_context":
            try:
                first = next(iter(out), None)
            except (StopIteration, TypeError):
                first = None
            if first is None:
                return iter([_FakeContextEntry()])
            return out
        if group == "opentelemetry_resource_detector" and name == "otel":
            try:
                first = next(iter(out), None)
            except (StopIteration, TypeError):
                first = None
            if first is None:
                return iter([_FakeOtelDetectorEntry()])
        return out

    _otel_meta.entry_points = _patched_entry_points


_install_patch()

# Pre-import chromadb after the patch so reme gets a valid module (avoids
# chromadb=None and AttributeError on chromadb.ClientAPI when reme loads).
# If this fails (e.g. on a different macOS than build host), surface the
# real error so users see e.g. "Library not loaded" instead of AttributeError.
try:
    import chromadb  # noqa: F401
    from chromadb.config import Settings  # noqa: F401
except Exception as _e:  # ImportError or OSError (dylib load fail)
    import traceback

    sys.stderr.write(
        "CoPaw runtime hook: chromadb pre-import failed (app may crash next).\n",
    )
    traceback.print_exc(file=sys.stderr)
    raise
