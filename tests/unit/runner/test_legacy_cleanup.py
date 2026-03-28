# -*- coding: utf-8 -*-
"""Unit tests verifying legacy logic removed after dual-queue migration.

Validates: Requirements 6.1, 7.1, 7.3
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# Source file paths
# ---------------------------------------------------------------------------

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "copaw" / "app"
_CONSOLE_PY = _SRC_ROOT / "routers" / "console.py"
_MANAGER_PY = _SRC_ROOT / "channels" / "manager.py"
_COMMAND_DISPATCH_PY = _SRC_ROOT / "runner" / "command_dispatch.py"


def _parse_module(path: Path) -> ast.Module:
    """Parse a Python source file into an AST module."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _top_level_names(tree: ast.Module) -> set[str]:
    """Return all top-level function and class names in an AST module."""
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
    return names


def _class_method_names(tree: ast.Module, class_name: str) -> set[str]:
    """Return all method names defined inside a class."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                n.name
                for n in ast.iter_child_nodes(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


# =========================================================================
# console.py: _handle_console_stop removed
# =========================================================================


class TestConsoleStopRemoved:
    """Verify _handle_console_stop no longer exists in console.py."""

    def test_no_handle_console_stop_in_ast(self):
        tree = _parse_module(_CONSOLE_PY)
        names = _top_level_names(tree)
        assert "_handle_console_stop" not in names

    def test_no_handle_console_stop_via_import(self):
        import copaw.app.routers.console as console_mod

        assert not hasattr(console_mod, "_handle_console_stop")


# =========================================================================
# manager.py: _handle_stop_fast_path removed
# =========================================================================


class TestManagerLegacyRemoved:
    """Verify _handle_stop_fast_path is gone; _active_process_tasks kept."""

    def test_no_handle_stop_fast_path_in_ast(self):
        tree = _parse_module(_MANAGER_PY)
        methods = _class_method_names(tree, "ChannelManager")
        assert "_handle_stop_fast_path" not in methods

    def test_no_handle_stop_fast_path_via_hasattr(self):
        from copaw.app.channels.manager import ChannelManager

        assert not hasattr(ChannelManager, "_handle_stop_fast_path")

    def test_active_process_tasks_retained_for_stop(self):
        """_active_process_tasks kept for /stop to cancel tasks."""
        from copaw.app.channels.manager import ChannelManager

        src = inspect.getsource(ChannelManager.__init__)
        assert "_active_process_tasks" in src


# =====================================================================
# command_dispatch.py: legacy functions removed
# =====================================================================


class TestCommandDispatchLegacyRemoved:
    """Verify replaced functions are gone from command_dispatch.py."""

    def test_no_run_command_path_in_ast(self):
        tree = _parse_module(_COMMAND_DISPATCH_PY)
        names = _top_level_names(tree)
        assert "run_command_path" not in names

    def test_no_is_command_in_ast(self):
        tree = _parse_module(_COMMAND_DISPATCH_PY)
        names = _top_level_names(tree)
        assert "_is_command" not in names

    def test_no_is_conversation_command_in_ast(self):
        tree = _parse_module(_COMMAND_DISPATCH_PY)
        names = _top_level_names(tree)
        assert "_is_conversation_command" not in names

    def test_no_run_command_path_via_import(self):
        import copaw.app.runner.command_dispatch as cd

        assert not hasattr(cd, "run_command_path")

    def test_no_is_command_via_import(self):
        import copaw.app.runner.command_dispatch as cd

        assert not hasattr(cd, "_is_command")

    def test_no_is_conversation_command_via_import(self):
        import copaw.app.runner.command_dispatch as cd

        assert not hasattr(cd, "_is_conversation_command")

    def test_get_last_user_text_still_exists(self):
        """_get_last_user_text should be retained."""
        import copaw.app.runner.command_dispatch as cd

        assert hasattr(cd, "_get_last_user_text")


# =========================================================================
# ChannelManager has new dual-queue attributes
# =========================================================================


class TestDualQueueAttributes:
    """Verify ChannelManager has the new dual-queue attributes."""

    def test_command_queues_attribute(self):
        from copaw.app.channels.manager import ChannelManager

        src = inspect.getsource(ChannelManager.__init__)
        assert "_command_queues" in src

    def test_command_router_attribute(self):
        from copaw.app.channels.manager import ChannelManager

        src = inspect.getsource(ChannelManager.__init__)
        assert "_command_router" in src

    def test_command_seq_attribute(self):
        from copaw.app.channels.manager import ChannelManager

        src = inspect.getsource(ChannelManager.__init__)
        assert "_command_seq" in src

    def test_set_command_router_method_exists(self):
        from copaw.app.channels.manager import ChannelManager

        assert hasattr(ChannelManager, "set_command_router")

    def test_consume_command_loop_method_exists(self):
        from copaw.app.channels.manager import ChannelManager

        assert hasattr(ChannelManager, "_consume_command_loop")

    def test_classify_command_method_exists(self):
        from copaw.app.channels.manager import ChannelManager

        assert hasattr(ChannelManager, "_classify_command")


# =========================================================================
# Commands go through CommandQueue path (enqueue routes to command queue)
# =========================================================================


class TestCommandsRouteToCommandQueue:
    """Verify commands are routed through the CommandQueue path."""

    def test_enqueue_one_references_classify_command(self):
        """_enqueue_one should call _classify_command for routing."""
        from copaw.app.channels.manager import ChannelManager

        # pylint: disable=protected-access
        src = inspect.getsource(ChannelManager._enqueue_one)
        assert "_classify_command" in src

    def test_enqueue_one_references_command_queues(self):
        """_enqueue_one should put commands into _command_queues."""
        from copaw.app.channels.manager import ChannelManager

        # pylint: disable=protected-access
        src = inspect.getsource(ChannelManager._enqueue_one)
        assert "_command_queues" in src

    def test_enqueue_one_no_is_stop_command(self):
        """_enqueue_one should not reference the old is_stop_command."""
        from copaw.app.channels.manager import ChannelManager

        # pylint: disable=protected-access
        src = inspect.getsource(ChannelManager._enqueue_one)
        assert "is_stop_command" not in src


class TestIsStopCommandRemoved:
    """Verify is_stop_command has been removed from daemon_commands."""

    def test_no_is_stop_command_in_ast(self):
        _DAEMON_COMMANDS_PY = _SRC_ROOT / "runner" / "daemon_commands.py"
        tree = _parse_module(_DAEMON_COMMANDS_PY)
        names = _top_level_names(tree)
        assert "is_stop_command" not in names

    def test_no_is_stop_command_via_import(self):
        import copaw.app.runner.daemon_commands as dc

        assert not hasattr(dc, "is_stop_command")


class TestRunDaemonStopRemoved:
    """Verify run_daemon_stop has been removed."""

    def test_no_run_daemon_stop_in_ast(self):
        _DC_PY = _SRC_ROOT / "runner" / "daemon_commands.py"
        tree = _parse_module(_DC_PY)
        names = _top_level_names(tree)
        assert "run_daemon_stop" not in names

    def test_no_run_daemon_stop_via_import(self):
        import copaw.app.runner.daemon_commands as dc

        assert not hasattr(dc, "run_daemon_stop")


class TestDaemonCommandHandlerMixinRemoved:
    """Verify DaemonCommandHandlerMixin has been removed."""

    def test_no_mixin_in_ast(self):
        _DC_PY = _SRC_ROOT / "runner" / "daemon_commands.py"
        tree = _parse_module(_DC_PY)
        names = _top_level_names(tree)
        assert "DaemonCommandHandlerMixin" not in names

    def test_no_mixin_via_import(self):
        import copaw.app.runner.daemon_commands as dc

        assert not hasattr(dc, "DaemonCommandHandlerMixin")
