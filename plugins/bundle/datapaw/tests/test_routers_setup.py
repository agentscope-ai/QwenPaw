# -*- coding: utf-8 -*-
"""Tests for plugins/bundle/datapaw/routers_setup.py."""
from unittest.mock import MagicMock, patch


def test_mount_routers_includes_tasks_router_without_extra_prefix():
    """tasks_router already carries /api/tasks; mount must not add another /api prefix."""
    from routers_setup import mount_routers

    fake_app = MagicMock()
    fake_app.routes = []
    fake_router = MagicMock(name="tasks_router", prefix="/api/tasks")

    with patch("routers_setup._find_fastapi_app", return_value=fake_app), \
         patch("routers_setup.tasks_router", fake_router), \
         patch("routers_setup._reorder_catch_all") as reorder:
        mount_routers()

    # include_router must be called without an additional prefix.
    fake_app.include_router.assert_called_once_with(fake_router)
    reorder.assert_called_once_with(fake_app)
    assert fake_app.middleware_stack is None, \
        "middleware_stack must be reset so new routes take effect"


def test_mount_routers_skips_when_app_unavailable():
    """Silently skip when no app instance is found; must not raise."""
    from routers_setup import mount_routers

    with patch("routers_setup._find_fastapi_app", return_value=None):
        mount_routers()  # must not raise


def test_reorder_catch_all_moves_spa_route_to_end():
    """SPA catch-all must move to the end so it doesn't shadow /api/* routes."""
    from routers_setup import _reorder_catch_all

    catch_all = MagicMock()
    catch_all.path = "/{full_path:path}"
    other = MagicMock()
    other.path = "/api/tasks"
    third = MagicMock()
    third.path = "/api/agents"

    fake_app = MagicMock()
    fake_app.routes = [catch_all, other, third]
    _reorder_catch_all(fake_app)

    assert fake_app.routes[-1] is catch_all
    assert fake_app.routes[0] is other
    assert fake_app.routes[1] is third


def test_reorder_catch_all_noop_when_no_catch_all():
    """No catch-all → routes list unchanged."""
    from routers_setup import _reorder_catch_all

    r1, r2 = MagicMock(), MagicMock()
    r1.path = "/api/tasks"
    r2.path = "/api/agents"

    fake_app = MagicMock()
    fake_app.routes = [r1, r2]
    _reorder_catch_all(fake_app)

    assert fake_app.routes == [r1, r2]
