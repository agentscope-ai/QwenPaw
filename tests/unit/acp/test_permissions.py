# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.acp.permissions import ACPPermissionAdapter
from copaw.acp.policy import is_obviously_dangerous_prompt


def test_acp_auto_approves_workspace_relative_read(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.acp.permissions.load_sensitive_files_from_config",
        lambda: [],
    )
    adapter = ACPPermissionAdapter("/repo", require_approval=True)

    # pylint: disable=protected-access
    assert adapter._should_auto_approve("read", {"path": "README.md"}) is True


def test_acp_does_not_auto_approve_path_traversal(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.acp.permissions.load_sensitive_files_from_config",
        lambda: [],
    )
    adapter = ACPPermissionAdapter("/repo", require_approval=True)

    # pylint: disable=protected-access
    assert (
        adapter._should_auto_approve(
            "read",
            {"path": "../../etc/passwd"},
        )
        is False
    )


def test_acp_does_not_auto_approve_sensitive_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.acp.permissions.load_sensitive_files_from_config",
        lambda: ["secrets/"],
    )
    adapter = ACPPermissionAdapter("/repo", require_approval=True)

    # pylint: disable=protected-access
    assert (
        adapter._should_auto_approve(
            "grep",
            {"path": "secrets/token.txt"},
        )
        is False
    )


def test_acp_requires_explicit_path_target(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.acp.permissions.load_sensitive_files_from_config",
        lambda: [],
    )
    adapter = ACPPermissionAdapter("/repo", require_approval=True)

    # pylint: disable=protected-access
    assert (
        adapter._should_auto_approve(
            "find",
            {"command": "find README.md"},
        )
        is False
    )


def test_acp_supports_nested_input_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.acp.permissions.load_sensitive_files_from_config",
        lambda: [],
    )
    adapter = ACPPermissionAdapter("/repo", require_approval=True)

    # pylint: disable=protected-access
    assert (
        adapter._should_auto_approve(
            "search",
            {"input": {"path": "docs/a.md"}},
        )
        is True
    )


def test_dangerous_prompt_ignores_safe_follow_up_reference() -> None:
    assert is_obviously_dangerous_prompt("刚才创建的文件内容是什么？") is False


def test_dangerous_prompt_still_flags_explicit_write_request() -> None:
    assert is_obviously_dangerous_prompt("创建一个新文件 note.txt") is True
