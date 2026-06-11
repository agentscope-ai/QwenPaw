# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for cloudpaw ``_reorder_catch_all``.

This helper was deleted by a bad merge while still being called from
``routers_setup.py``. It moves the SPA catch-all route
(``/{full_path:path}``) to the end of ``app.routes`` so concrete API
routes registered later are still reachable.

The helper only touches ``app.routes`` and reads ``route.path`` via
``getattr``, so it can be exercised with lightweight duck-typed fakes —
no FastAPI / Starlette / agentscope required.
"""

from types import SimpleNamespace

from plugins.bundle.cloudpaw.routers_setup import _reorder_catch_all


def _route(path):
    """Build a minimal route-like object with a ``path`` attribute."""
    return SimpleNamespace(path=path)


def _make_app(paths):
    """Build a minimal app-like object exposing a mutable ``routes`` list."""
    return SimpleNamespace(routes=[_route(p) for p in paths])


def _paths(app):
    return [r.path for r in app.routes]


def test_catch_all_moved_to_end():
    """Catch-all in the middle is moved to the final position."""
    app = _make_app(
        [
            "/{full_path:path}",
            "/api/agents",
            "/api/chat",
        ],
    )

    _reorder_catch_all(app)

    assert _paths(app)[-1] == "/{full_path:path}"
    # Concrete routes are preserved and now precede the fallback.
    assert _paths(app) == ["/api/agents", "/api/chat", "/{full_path:path}"]


def test_already_last_is_noop():
    """Catch-all already at the end stays at the end; order preserved."""
    app = _make_app(
        [
            "/api/agents",
            "/api/chat",
            "/{full_path:path}",
        ],
    )

    _reorder_catch_all(app)

    assert _paths(app) == ["/api/agents", "/api/chat", "/{full_path:path}"]


def test_no_catch_all_leaves_routes_untouched():
    """Absence of a catch-all route is a no-op."""
    app = _make_app(["/api/agents", "/api/chat"])

    _reorder_catch_all(app)

    assert _paths(app) == ["/api/agents", "/api/chat"]


def test_count_preserved():
    """Reordering never adds or drops routes."""
    app = _make_app(
        [
            "/{full_path:path}",
            "/api/a",
            "/api/b",
            "/api/c",
        ],
    )

    _reorder_catch_all(app)

    assert len(app.routes) == 4
    assert _paths(app)[-1] == "/{full_path:path}"


def test_routes_without_path_attr_are_ignored():
    """Routes lacking a ``path`` attribute do not raise and are kept."""
    app = SimpleNamespace(
        routes=[
            object(),  # no ``path`` attribute -> getattr default ""
            _route("/api/agents"),
            _route("/{full_path:path}"),
        ],
    )

    _reorder_catch_all(app)

    assert app.routes[-1].path == "/{full_path:path}"
    assert len(app.routes) == 3
