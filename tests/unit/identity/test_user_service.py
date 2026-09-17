# -*- coding: utf-8 -*-
"""Task 2.1 用户与密码服务契约。"""

from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.exc import IntegrityError

from qwenpaw.identity.governance import LastActiveAdminError
from qwenpaw.identity.models import (
    CredentialRecord,
    LegacyAdminCredential,
    PlatformRole,
    UserProfileUpdate,
    UserRecord,
)
from qwenpaw.identity.passwords import PasswordManager
from qwenpaw.identity.repository import (
    DuplicateUsernameError,
    PostgresUserRepository,
)
from qwenpaw.identity.service import (
    CurrentPasswordIncorrectError,
    SelfRegistrationDisabledError,
    UserService,
)


class FakeUserRepository:
    def __init__(self) -> None:
        self.credentials: dict[str, CredentialRecord] = {}
        self.password_updates: list[UUID] = []
        self.login_updates: list[UUID] = []

    async def count_users(self) -> int:
        return len(self.credentials)

    async def create_credential(
        self,
        *,
        username: str,
        password_hash: str,
        platform_role: PlatformRole,
    ) -> CredentialRecord:
        if username in self.credentials:
            raise DuplicateUsernameError(username)
        effective_role = platform_role if self.credentials else PlatformRole.ADMIN
        credential = CredentialRecord(
            user=UserRecord(
                id=uuid4(),
                username=username,
                platform_role=effective_role,
                status="active",
            ),
            password_hash=password_hash,
        )
        self.credentials[username] = credential
        return credential

    async def create_legacy_admin_if_empty(
        self,
        *,
        username: str,
        password_hash: str,
    ) -> CredentialRecord | None:
        if self.credentials:
            return None
        return await self.create_credential(
            username=username,
            password_hash=password_hash,
            platform_role=PlatformRole.ADMIN,
        )

    async def get_credential_by_username(
        self,
        username: str,
    ) -> CredentialRecord | None:
        return self.credentials.get(username)

    async def get_credential_by_user_id(
        self,
        user_id: UUID,
    ) -> CredentialRecord | None:
        return next(
            (
                credential
                for credential in self.credentials.values()
                if credential.user.id == user_id
            ),
            None,
        )

    async def update_profile(self, user_id: UUID, profile: UserProfileUpdate):
        for username, credential in list(self.credentials.items()):
            if credential.user.id != user_id:
                continue
            if profile.username != username and profile.username in self.credentials:
                raise DuplicateUsernameError(profile.username)
            updated = replace(credential.user, **asdict(profile))
            del self.credentials[username]
            self.credentials[profile.username] = replace(credential, user=updated)
            return updated
        raise AssertionError("unknown user")

    async def update_password_hash(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> None:
        for username, credential in self.credentials.items():
            if credential.user.id == user_id:
                self.credentials[username] = replace(
                    credential,
                    password_hash=password_hash,
                )
                self.password_updates.append(user_id)
                return
        raise AssertionError("unknown user")

    async def mark_login(self, user_id: UUID) -> None:
        self.login_updates.append(user_id)

    def disable(self, username: str) -> None:
        credential = self.credentials[username]
        self.credentials[username] = replace(
            credential,
            user=replace(credential.user, status="disabled"),
        )


class ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self):
        return self.value


class MappingResult:
    def __init__(self, value: dict[str, object] | None) -> None:
        self.value = value

    def mappings(self):
        return self

    def one(self) -> dict[str, object]:
        assert self.value is not None
        return self.value

    def one_or_none(self) -> dict[str, object] | None:
        return self.value


class MappingListResult:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self.values = values

    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return self.values


class RecordingSession:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.statements: list[tuple[str, dict[str, object] | None]] = []

    async def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def session_factory(session: RecordingSession):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


@pytest.mark.asyncio
async def test_first_user_is_forced_to_admin_and_hash_is_not_exposed() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)

    user = await service.create_user(
        " owner ",
        "correct horse battery staple",
        PlatformRole.MEMBER,
    )

    assert user.username == "owner"
    assert user.platform_role is PlatformRole.ADMIN
    assert not hasattr(user, "password_hash")
    stored_hash = repository.credentials["owner"].password_hash
    assert stored_hash.startswith("$argon2id$")
    assert "correct horse battery staple" not in stored_hash


@pytest.mark.asyncio
async def test_subsequent_user_keeps_requested_role_and_username_is_unique() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    await service.create_user("admin", "admin-password", PlatformRole.ADMIN)

    member = await service.create_user(
        "member",
        "member-password",
        PlatformRole.MEMBER,
    )

    assert member.platform_role is PlatformRole.MEMBER
    with pytest.raises(DuplicateUsernameError):
        await service.create_user(
            "member",
            "different-password",
            PlatformRole.MEMBER,
        )


@pytest.mark.asyncio
async def test_authenticate_accepts_valid_active_user_without_logging_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    user = await service.create_user(
        "admin",
        "never-log-this-password",
        PlatformRole.ADMIN,
    )

    with caplog.at_level(logging.INFO, logger="qwenpaw.identity.service"):
        authenticated = await service.authenticate(
            "admin",
            "never-log-this-password",
        )

    assert authenticated == user
    assert repository.login_updates == [user.id]
    assert "never-log-this-password" not in caplog.text


@pytest.mark.asyncio
async def test_disabled_user_is_rejected_before_password_verification() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    await service.create_user("admin", "admin-password", PlatformRole.ADMIN)
    repository.disable("admin")

    assert await service.authenticate("admin", "admin-password") is None
    assert repository.login_updates == []


@pytest.mark.asyncio
async def test_wrong_password_returns_none_without_changing_hash() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    await service.create_user("admin", "admin-password", PlatformRole.ADMIN)
    original_hash = repository.credentials["admin"].password_hash

    assert await service.authenticate("admin", "wrong-password") is None
    assert repository.credentials["admin"].password_hash == original_hash
    assert repository.password_updates == []


@pytest.mark.asyncio
async def test_profile_update_normalizes_enterprise_fields() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    user = await service.create_user("alice", "OldPass!2026", PlatformRole.ADMIN)

    updated = await service.update_profile(
        user.id,
        UserProfileUpdate(
            username=" alice-renamed ",
            display_name=" Alice Chen ",
            email=" ALICE@EXAMPLE.COM ",
            phone=" +86 (138) 0000-0000 ",
            department=" 研发部 ",
            job_title=" 平台工程师 ",
            remark=" 企业账户 ",
        ),
    )

    assert updated.username == "alice-renamed"
    assert updated.display_name == "Alice Chen"
    assert updated.email == "alice@example.com"
    assert updated.phone == "+86 (138) 0000-0000"
    assert updated.department == "研发部"
    assert updated.job_title == "平台工程师"
    assert updated.remark == "企业账户"


@pytest.mark.asyncio
async def test_profile_update_rejects_invalid_email_and_phone() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    user = await service.create_user("alice", "OldPass!2026", PlatformRole.ADMIN)

    with pytest.raises(ValueError, match="invalid_email"):
        await service.update_profile(
            user.id,
            UserProfileUpdate(username="alice", email="invalid"),
        )
    with pytest.raises(ValueError, match="invalid_phone"):
        await service.update_profile(
            user.id,
            UserProfileUpdate(username="alice", phone="138ABC"),
        )


@pytest.mark.asyncio
async def test_change_password_requires_current_password() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    user = await service.create_user("alice", "OldPass!2026", PlatformRole.ADMIN)
    repository.password_updates.clear()

    with pytest.raises(CurrentPasswordIncorrectError):
        await service.change_password(user.id, "wrong", "NewPass!2026")

    assert repository.password_updates == []


@pytest.mark.asyncio
async def test_change_and_reset_password_replace_hash() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    user = await service.create_user("alice", "OldPass!2026", PlatformRole.ADMIN)
    original_hash = repository.credentials["alice"].password_hash
    repository.password_updates.clear()

    await service.change_password(user.id, "OldPass!2026", "NewPass!2026")
    changed_hash = repository.credentials["alice"].password_hash
    assert changed_hash != original_hash
    assert repository.password_updates == [user.id]

    await service.reset_password(user.id, "AdminReset!2026")
    assert repository.credentials["alice"].password_hash != changed_hash
    assert repository.password_updates == [user.id, user.id]


@pytest.mark.asyncio
async def test_outdated_argon2_parameters_upgrade_after_successful_login() -> None:
    repository = FakeUserRepository()
    stale_hasher = PasswordHash(
        (
            Argon2Hasher(
                time_cost=1,
                memory_cost=8192,
                parallelism=1,
            ),
        )
    )
    stale_hash = stale_hasher.hash("admin-password")
    credential = await repository.create_credential(
        username="admin",
        password_hash=stale_hash,
        platform_role=PlatformRole.ADMIN,
    )

    authenticated = await UserService(repository).authenticate(
        "admin",
        "admin-password",
    )

    updated_hash = repository.credentials["admin"].password_hash
    assert authenticated == credential.user
    assert updated_hash != stale_hash
    assert updated_hash.startswith("$argon2id$")
    assert repository.password_updates == [credential.user.id]


@pytest.mark.asyncio
async def test_legacy_sha256_admin_migrates_once_and_upgrades_on_login() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    salt = "00112233445566778899aabbccddeeff"
    legacy_hash = hashlib.sha256((salt + "legacy-password").encode("utf-8")).hexdigest()
    legacy = LegacyAdminCredential(
        username="legacy-admin",
        password_hash=legacy_hash,
        password_salt=salt,
    )

    migrated = await service.migrate_legacy_admin(legacy)

    assert migrated is not None
    assert migrated.platform_role is PlatformRole.ADMIN
    stored_legacy = repository.credentials["legacy-admin"].password_hash
    assert stored_legacy.startswith(PasswordManager.LEGACY_SHA256_PREFIX)

    authenticated = await service.authenticate(
        "legacy-admin",
        "legacy-password",
    )

    assert authenticated == migrated
    upgraded = repository.credentials["legacy-admin"].password_hash
    assert upgraded.startswith("$argon2id$")
    assert "legacy-password" not in upgraded
    assert repository.password_updates == [migrated.id]


@pytest.mark.asyncio
async def test_legacy_auth_data_is_only_used_when_no_users_exist() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    await service.create_user("admin", "admin-password", PlatformRole.ADMIN)
    legacy = LegacyAdminCredential.from_auth_data(
        {
            "user": {
                "username": "legacy-admin",
                "password_hash": "a" * 64,
                "password_salt": "b" * 32,
            },
            "jwt_secret": "must-not-be-migrated",
        }
    )

    assert legacy is not None
    assert await service.migrate_legacy_admin(legacy) is None
    assert set(repository.credentials) == {"admin"}


@pytest.mark.asyncio
async def test_self_registration_is_disabled_by_default() -> None:
    service = UserService(FakeUserRepository())

    with pytest.raises(SelfRegistrationDisabledError):
        await service.self_register("member", "member-password")


@pytest.mark.asyncio
async def test_repository_decides_first_user_role_inside_creation_lock() -> None:
    class StaleCountRepository(FakeUserRepository):
        async def count_users(self) -> int:
            return 0

    repository = StaleCountRepository()
    await repository.create_credential(
        username="concurrent-admin",
        password_hash="$argon2id$existing",
        platform_role=PlatformRole.ADMIN,
    )

    member = await UserService(repository).create_user(
        "member",
        "member-password",
        PlatformRole.MEMBER,
    )

    assert member.platform_role is PlatformRole.MEMBER


@pytest.mark.asyncio
async def test_legacy_migration_uses_atomic_empty_repository_operation() -> None:
    class ConcurrentRepository(FakeUserRepository):
        async def count_users(self) -> int:
            return 0

    repository = ConcurrentRepository()
    await repository.create_credential(
        username="concurrent-admin",
        password_hash="$argon2id$existing",
        platform_role=PlatformRole.ADMIN,
    )
    legacy = LegacyAdminCredential(
        username="legacy-admin",
        password_hash="a" * 64,
        password_salt="b" * 32,
    )

    migrated = await UserService(repository).migrate_legacy_admin(legacy)

    assert migrated is None
    assert set(repository.credentials) == {"concurrent-admin"}


@pytest.mark.asyncio
async def test_postgres_repository_scopes_reads_to_selected_schema() -> None:
    user_id = uuid4()
    session = RecordingSession(
        [
            ScalarResult(1),
            MappingResult(
                {
                    "id": user_id,
                    "username": "admin",
                    "password_hash": "$argon2id$example",
                    "platform_role": "admin",
                    "status": "active",
                }
            ),
        ]
    )
    repository = PostgresUserRepository(
        schema="identity_test",
        session_factory=session_factory(session),
    )

    assert await repository.count_users() == 1
    credential = await repository.get_credential_by_username("admin")

    assert credential is not None
    assert credential.user.id == user_id
    assert credential.user.platform_role is PlatformRole.ADMIN
    assert all(
        '"identity_test".users' in statement for statement, _ in session.statements
    )


@pytest.mark.asyncio
async def test_postgres_repository_forces_first_user_admin_inside_lock() -> None:
    user_id = uuid4()
    session = RecordingSession(
        [
            ScalarResult(None),
            ScalarResult(False),
            MappingResult(
                {
                    "id": user_id,
                    "username": "owner",
                    "password_hash": "$argon2id$example",
                    "platform_role": "admin",
                    "status": "active",
                }
            ),
        ]
    )
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    credential = await repository.create_credential(
        username="owner",
        password_hash="$argon2id$example",
        platform_role=PlatformRole.MEMBER,
    )

    assert credential.user.platform_role is PlatformRole.ADMIN
    assert "pg_advisory_xact_lock" in session.statements[0][0]
    insert_parameters = session.statements[2][1]
    assert insert_parameters is not None
    assert insert_parameters["platform_role"] == "admin"


@pytest.mark.asyncio
async def test_postgres_repository_keeps_member_role_after_first_user() -> None:
    user_id = uuid4()
    session = RecordingSession(
        [
            ScalarResult(None),
            ScalarResult(True),
            MappingResult(
                {
                    "id": user_id,
                    "username": "member",
                    "password_hash": "$argon2id$example",
                    "platform_role": "member",
                    "status": "active",
                }
            ),
        ]
    )
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    credential = await repository.create_credential(
        username="member",
        password_hash="$argon2id$example",
        platform_role=PlatformRole.MEMBER,
    )

    assert credential.user.platform_role is PlatformRole.MEMBER
    assert session.statements[2][1]["platform_role"] == "member"


@pytest.mark.asyncio
async def test_postgres_legacy_migration_refuses_nonempty_user_table() -> None:
    session = RecordingSession([ScalarResult(None), ScalarResult(True)])
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    credential = await repository.create_legacy_admin_if_empty(
        username="legacy-admin",
        password_hash="legacy_salted_sha256$example",
    )

    assert credential is None
    assert len(session.statements) == 2
    assert all("INSERT" not in statement for statement, _ in session.statements)


@pytest.mark.asyncio
async def test_postgres_repository_updates_only_hash_and_login_timestamp() -> None:
    session = RecordingSession([ScalarResult(None), ScalarResult(None)])
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
        clock=lambda: datetime(2026, 8, 21, 3, 30, tzinfo=UTC),
    )
    user_id = uuid4()

    await repository.update_password_hash(user_id, "$argon2id$new")
    await repository.mark_login(user_id)

    assert 'UPDATE "qwenpaw".users' in session.statements[0][0]
    assert session.statements[0][1] == {
        "user_id": user_id,
        "password_hash": "$argon2id$new",
    }
    assert "last_login_at" in session.statements[1][0]
    assert session.statements[1][1] == {
        "user_id": user_id,
        "logged_in_at": datetime(2026, 8, 21, 3, 30, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_postgres_repository_lists_public_users_without_password_hash() -> None:
    admin_id = uuid4()
    session = RecordingSession(
        [
            MappingListResult(
                [
                    {
                        "id": admin_id,
                        "username": "admin",
                        "platform_role": "admin",
                        "status": "active",
                    }
                ]
            )
        ]
    )
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    users = await repository.list_users()

    assert users == [
        UserRecord(
            id=admin_id,
            username="admin",
            platform_role=PlatformRole.ADMIN,
            status="active",
        )
    ]
    assert "password_hash" not in session.statements[0][0]


@pytest.mark.asyncio
async def test_postgres_repository_reads_and_updates_public_profile_fields() -> None:
    user_id = uuid4()
    created_at = datetime(2026, 8, 21, 3, 30, tzinfo=UTC)
    updated_at = datetime(2026, 9, 9, 4, 30, tzinfo=UTC)
    last_login_at = datetime(2026, 9, 9, 4, 20, tzinfo=UTC)
    row = {
        "id": user_id,
        "username": "alice",
        "platform_role": "member",
        "status": "active",
        "display_name": "Alice Chen",
        "email": "alice@example.com",
        "phone": "+86 138-0000-0000",
        "department": "研发部",
        "job_title": "平台工程师",
        "remark": "维护账户平台",
        "created_at": created_at,
        "updated_at": updated_at,
        "last_login_at": last_login_at,
    }
    session = RecordingSession([MappingResult(row)])
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    updated = await repository.update_profile(
        user_id,
        UserProfileUpdate(
            username="alice",
            display_name="Alice Chen",
            email="alice@example.com",
            phone="+86 138-0000-0000",
            department="研发部",
            job_title="平台工程师",
            remark="维护账户平台",
        ),
    )

    assert updated == UserRecord(
        id=user_id,
        username="alice",
        platform_role=PlatformRole.MEMBER,
        status="active",
        display_name="Alice Chen",
        email="alice@example.com",
        phone="+86 138-0000-0000",
        department="研发部",
        job_title="平台工程师",
        remark="维护账户平台",
        created_at=created_at,
        updated_at=updated_at,
        last_login_at=last_login_at,
    )
    statement, parameters = session.statements[0]
    assert "password_hash" not in statement
    assert parameters == {
        "user_id": user_id,
        "username": "alice",
        "display_name": "Alice Chen",
        "email": "alice@example.com",
        "phone": "+86 138-0000-0000",
        "department": "研发部",
        "job_title": "平台工程师",
        "remark": "维护账户平台",
    }


@pytest.mark.asyncio
async def test_postgres_repository_rejects_disabling_last_active_admin() -> None:
    admin_id = uuid4()
    session = RecordingSession(
        [
            ScalarResult(None),
            MappingResult(
                {
                    "id": admin_id,
                    "username": "admin",
                    "platform_role": "admin",
                    "status": "active",
                }
            ),
            ScalarResult(1),
        ]
    )
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    with pytest.raises(LastActiveAdminError):
        await repository.update_status(admin_id, "disabled")

    assert all(
        not statement.lstrip().startswith("UPDATE")
        for statement, _ in session.statements
    )
    assert "FOR UPDATE" in session.statements[1][0]


@pytest.mark.asyncio
async def test_postgres_repository_rejects_demoting_last_active_admin() -> None:
    admin_id = uuid4()
    session = RecordingSession(
        [
            ScalarResult(None),
            MappingResult(
                {
                    "id": admin_id,
                    "username": "admin",
                    "platform_role": "admin",
                    "status": "active",
                }
            ),
            ScalarResult(1),
        ]
    )
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    with pytest.raises(LastActiveAdminError):
        await repository.update_role(admin_id, PlatformRole.MEMBER)

    assert all(
        not statement.lstrip().startswith("UPDATE")
        for statement, _ in session.statements
    )


@pytest.mark.asyncio
async def test_postgres_repository_maps_unique_conflict_to_domain_error() -> None:
    class UniqueViolation(Exception):
        sqlstate = "23505"

    session = RecordingSession(
        [
            ScalarResult(None),
            ScalarResult(True),
            IntegrityError("INSERT", {}, UniqueViolation("unique violation")),
        ]
    )
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    with pytest.raises(DuplicateUsernameError):
        await repository.create_credential(
            username="member",
            password_hash="$argon2id$example",
            platform_role=PlatformRole.MEMBER,
        )


@pytest.mark.asyncio
async def test_postgres_repository_does_not_mask_other_integrity_errors() -> None:
    class CheckViolation(Exception):
        sqlstate = "23514"

    error = IntegrityError("INSERT", {}, CheckViolation("check violation"))
    session = RecordingSession([ScalarResult(None), ScalarResult(True), error])
    repository = PostgresUserRepository(
        schema="qwenpaw",
        session_factory=session_factory(session),
    )

    with pytest.raises(IntegrityError) as caught:
        await repository.create_credential(
            username="member",
            password_hash="$argon2id$example",
            platform_role=PlatformRole.MEMBER,
        )

    assert caught.value is error
