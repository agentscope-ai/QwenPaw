# -*- coding: utf-8 -*-
"""WorkspaceResolver 的授权资源与路径隔离矩阵。"""

from pathlib import Path
from uuid import UUID

import pytest

from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.workspaces.resolver import (
    WorkspaceKind,
    WorkspaceResolutionDenied,
    WorkspaceResolver,
)


USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
APP_ID = UUID("33333333-3333-4333-8333-333333333333")
PUBLICATION_ID = UUID("44444444-4444-4444-8444-444444444444")


def test_resolves_managed_workspace_kinds_from_resource_ids(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)

    draft = resolver.resolve(
        kind=WorkspaceKind.DRAFT,
        resource_id="agent-a",
        workspace_key="workspaces/agent-a",
    )
    published = resolver.resolve(
        kind=WorkspaceKind.PUBLISHED_BASELINE,
        resource_id="publication-a",
        workspace_key="published_workspaces/publication-a",
    )
    runtime = resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id="agent-a",
        actor_user_id=USER_A,
        workspace_key=f"user_workspaces/{USER_A}/agent-a",
    )

    assert draft.path == tmp_path / "workspaces" / "agent-a"
    assert draft.read_only is False
    assert published.path == (
        tmp_path / "published_workspaces" / "publication-a"
    )
    assert published.read_only is True
    assert runtime.path == tmp_path / "user_workspaces" / str(USER_A) / "agent-a"
    assert runtime.read_only is False


def test_resolves_shared_app_runtime_from_server_ids(tmp_path: Path) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)

    runtime = resolver.resolve_shared_app_runtime(
        user_id=USER_A,
        shared_app_id=APP_ID,
        publication_id=PUBLICATION_ID,
        workspace_key=(
            f"user_workspaces/{USER_A}/apps/{APP_ID}/{PUBLICATION_ID}"
        ),
    )

    assert runtime.kind is WorkspaceKind.SHARED_APP_RUNTIME
    assert runtime.path == (
        tmp_path
        / "user_workspaces"
        / str(USER_A)
        / "apps"
        / str(APP_ID)
        / str(PUBLICATION_ID)
    )
    assert runtime.read_only is False


def test_rejects_cross_user_shared_app_runtime_key(tmp_path: Path) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)

    with pytest.raises(WorkspaceResolutionDenied, match="workspace_key_mismatch"):
        resolver.resolve_shared_app_runtime(
            user_id=USER_A,
            shared_app_id=APP_ID,
            publication_id=PUBLICATION_ID,
            workspace_key=(
                f"user_workspaces/{USER_B}/apps/{APP_ID}/{PUBLICATION_ID}"
            ),
        )


@pytest.mark.parametrize(
    ("kind", "resource_id", "actor_user_id", "workspace_key"),
    [
        (WorkspaceKind.DRAFT, "agent-a", None, "/tmp/agent-a"),
        (WorkspaceKind.DRAFT, "agent-a", None, "workspaces/../agent-a"),
        (WorkspaceKind.DRAFT, "../agent-a", None, None),
        (
            WorkspaceKind.USER_RUNTIME,
            "agent-a",
            USER_A,
            f"user_workspaces/{USER_B}/agent-a",
        ),
    ],
)
def test_rejects_untrusted_or_cross_user_workspace_keys(
    tmp_path: Path,
    kind: WorkspaceKind,
    resource_id: str,
    actor_user_id: UUID | None,
    workspace_key: str | None,
) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)

    with pytest.raises(WorkspaceResolutionDenied):
        resolver.resolve(
            kind=kind,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            workspace_key=workspace_key,
        )


def test_rejects_symlink_escape_from_managed_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    managed_root = tmp_path / "workspaces"
    managed_root.mkdir()
    link = managed_root / "agent-a"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建目录符号链接")

    resolver = WorkspaceResolver(working_dir=tmp_path)

    with pytest.raises(
        WorkspaceResolutionDenied,
        match="workspace_symlink_denied",
    ):
        resolver.resolve(kind=WorkspaceKind.DRAFT, resource_id="agent-a")


def test_registered_legacy_workspace_continues_to_work(tmp_path: Path) -> None:
    legacy_root = tmp_path.parent / f"{tmp_path.name}-legacy-agent"
    resolver = WorkspaceResolver(
        working_dir=tmp_path,
        legacy_workspaces={"legacy-agent": legacy_root},
    )

    resolved = resolver.resolve(
        kind=WorkspaceKind.LEGACY,
        resource_id="legacy-agent",
        workspace_key=str(legacy_root),
    )

    assert resolved.path == legacy_root.resolve()
    assert resolved.workspace_key == str(legacy_root)
    assert resolved.kind is WorkspaceKind.LEGACY


def test_unregistered_legacy_absolute_path_is_denied(tmp_path: Path) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)

    with pytest.raises(
        WorkspaceResolutionDenied,
        match="legacy_workspace_not_registered",
    ):
        resolver.resolve(
            kind=WorkspaceKind.LEGACY,
            resource_id="legacy-agent",
            workspace_key=str(tmp_path.parent / "unregistered"),
        )


def test_registered_legacy_symlink_is_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-legacy-target"
    outside.mkdir()
    link = tmp_path.parent / f"{tmp_path.name}-legacy-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建目录符号链接")

    with pytest.raises(
        WorkspaceResolutionDenied,
        match="workspace_symlink_denied",
    ):
        WorkspaceResolver(
            working_dir=tmp_path,
            legacy_workspaces={"legacy-agent": link},
        )


def test_workspace_preserves_resolution_metadata(tmp_path: Path) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)
    resolved = resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id="agent-a",
        actor_user_id=USER_A,
    )

    workspace = Workspace(agent_id="agent-a", workspace_dir=resolved)

    assert workspace.workspace_dir == resolved.path
    assert workspace.workspace_kind == WorkspaceKind.USER_RUNTIME.value
    assert workspace.workspace_key == resolved.workspace_key
    assert workspace.workspace_read_only is False


def test_workspace_does_not_create_missing_read_only_baseline(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)
    resolved = resolver.resolve(
        kind=WorkspaceKind.PUBLISHED_BASELINE,
        resource_id="publication-a",
    )

    with pytest.raises(FileNotFoundError):
        Workspace(agent_id="agent-a", workspace_dir=resolved)

    assert not resolved.path.exists()


def test_standard_directories_are_initialized_for_user_runtime(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)
    runtime = resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id="agent-a",
        actor_user_id=USER_A,
    )

    root = resolver.ensure_standard_directories(runtime)

    assert (root / "media").is_dir()
    assert (root / "artifacts").is_dir()
    assert not (root / "资料").exists()
    assert not (root / "产物").exists()


def test_standard_directories_copy_legacy_artifacts_without_overwriting(
    tmp_path: Path,
) -> None:
    resolver = WorkspaceResolver(working_dir=tmp_path)
    runtime = resolver.resolve(
        kind=WorkspaceKind.USER_RUNTIME,
        resource_id="agent-a",
        actor_user_id=USER_A,
    )
    runtime.path.mkdir(parents=True)
    legacy = runtime.path / "产物"
    legacy.mkdir()
    (legacy / "历史.md").write_text("legacy", encoding="utf-8")
    artifacts = runtime.path / "artifacts"
    artifacts.mkdir()
    (artifacts / "历史.md").write_text("current", encoding="utf-8")
    (legacy / "补充.md").write_text("copied", encoding="utf-8")

    resolver.ensure_standard_directories(runtime)

    assert (artifacts / "历史.md").read_text(encoding="utf-8") == "current"
    assert (artifacts / "补充.md").read_text(encoding="utf-8") == "copied"
    assert legacy.is_dir()


def test_standard_directories_do_not_modify_published_baseline(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "published_workspaces" / "publication-a"
    baseline_root.mkdir(parents=True)
    resolver = WorkspaceResolver(working_dir=tmp_path)
    baseline = resolver.resolve(
        kind=WorkspaceKind.PUBLISHED_BASELINE,
        resource_id="publication-a",
    )

    with pytest.raises(
        WorkspaceResolutionDenied,
        match="published_workspace_read_only",
    ):
        resolver.ensure_standard_directories(baseline)

    assert not (baseline_root / "media").exists()
