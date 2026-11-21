"""Windows Python 3.11 junction 不能把本人登记重定向到另一用户目录。"""

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.attachments.service import resolve_owned_attachment_path
from qwenpaw.app.chats.repo import AttachmentRecord
from qwenpaw.artifacts.service import reject_symlink_path
from qwenpaw.identity.models import PlatformRole
from qwenpaw.memory_scope.models import MemoryScopeDenied
from qwenpaw.memory_scope.resolver import MemoryScopeResolver
from qwenpaw.personal_library.paths import PersonalLibraryPathDenied, PersonalLibraryPathResolver
from qwenpaw.personal_library.derived_index import LibraryIndexStore
from qwenpaw.workspaces.resolver import WorkspaceKind, WorkspaceResolver


@pytest.fixture
def junction(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    created = []

    def create(link: Path, target: Path):
        assert link.absolute().is_relative_to(tmp_path.absolute())
        assert target.absolute().is_relative_to(tmp_path.absolute())
        link.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(WELDON_TEST_JUNCTION_LINK=str(link), WELDON_TEST_JUNCTION_TARGET=str(target))
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "New-Item -ItemType Junction -Path $env:WELDON_TEST_JUNCTION_LINK "
             "-Target $env:WELDON_TEST_JUNCTION_TARGET -ErrorAction Stop | Out-Null"],
            env=environment, capture_output=True, creationflags=0x08000000,
        )
        if result.returncode:
            pytest.skip("The platform does not permit junction creation")
        created.append(link)
        return link

    yield create
    for link in reversed(created):
        # rmdir removes only our verified synthetic junction, never its target.
        assert link.absolute().is_relative_to(tmp_path.absolute())
        os.rmdir(link)


def test_shared_guard_rejects_windows_junction(tmp_path, junction):
    alias = junction(tmp_path / "alias", tmp_path / "target")
    with pytest.raises(ValueError):
        reject_symlink_path(alias / "future-file.md")


def test_owned_attachment_cannot_follow_another_users_runtime_junction(tmp_path, junction):
    owner, foreign = uuid4(), uuid4()
    target = tmp_path / "user_workspaces" / str(foreign) / "reporter"
    (target / "media").mkdir(parents=True)
    (target / "media" / "report.md").write_text("other-account-content", encoding="utf-8")
    alias = junction(tmp_path / "user_workspaces" / str(owner) / "reporter", target)
    record = AttachmentRecord(
        id=uuid4(), owner_user_id=owner, agent_id=agent_database_id("reporter"),
        storage_key=str(alias / "media" / "report.md"), original_name="report.md",
        media_type="text/markdown", size=21, content_hash="original-owner-content",
        lifecycle="temporary", created_at=datetime.now(UTC),
    )
    with pytest.raises(FileNotFoundError):
        resolve_owned_attachment_path(record, owner_user_id=owner, working_dir=tmp_path)


@pytest.mark.parametrize("level", ["user", "agent"])
def test_workspace_resolver_rejects_junction_into_another_owned_domain(tmp_path, junction, level):
    owner, foreign = uuid4(), uuid4()
    alias = tmp_path / "user_workspaces" / str(owner)
    target = tmp_path / "user_workspaces" / str(foreign)
    if level == "agent":
        alias /= "reporter"
        target /= "reporter"
    junction(alias, target)
    with pytest.raises(ValueError):
        WorkspaceResolver(working_dir=tmp_path).resolve(
            kind=WorkspaceKind.USER_RUNTIME, resource_id="reporter", actor_user_id=owner,
        )


def test_private_memory_cannot_follow_a_user_root_junction(tmp_path, junction):
    owner, foreign = uuid4(), uuid4()
    target = tmp_path / "user_workspaces" / str(foreign)
    (target / "reporter" / "memory").mkdir(parents=True)
    junction(tmp_path / "user_workspaces" / str(owner), target)
    actor = ActorContext(user_id=owner, actor_type=ActorType.USER,
                         platform_role=PlatformRole.MEMBER, admin_mode=False, request_id="junction-test")
    resolver = MemoryScopeResolver(working_dir=tmp_path)
    context = resolver.resolve_private(actor=actor, agent_id="reporter")
    with pytest.raises(MemoryScopeDenied):
        resolver.existing_workspace(context)
    with pytest.raises(MemoryScopeDenied):
        resolver.ensure_workspace(context)


def test_private_library_cannot_follow_another_users_library_junction(tmp_path, junction):
    owner, foreign, agent = uuid4(), uuid4(), agent_database_id("reporter")
    target = tmp_path / "user_libraries" / str(foreign) / str(agent)
    target.mkdir(parents=True)
    (target / "report.md").write_text("other-account-content", encoding="utf-8")
    junction(tmp_path / "user_libraries" / str(owner) / str(agent), target)
    with pytest.raises(PersonalLibraryPathDenied):
        PersonalLibraryPathResolver(working_dir=tmp_path).resolve(
            user_id=owner, agent_id=agent, relative_path="report.md",
        )


def test_private_library_index_cannot_follow_another_users_index_junction(tmp_path, junction):
    owner, foreign, agent = uuid4(), uuid4(), agent_database_id("reporter")
    target = tmp_path / "personal_library_indexes" / str(foreign) / str(agent)
    junction(tmp_path / "personal_library_indexes" / str(owner) / str(agent), target)
    with pytest.raises(PersonalLibraryPathDenied):
        LibraryIndexStore(tmp_path, owner, agent)
    assert not (target / "search.sqlite3").exists()
