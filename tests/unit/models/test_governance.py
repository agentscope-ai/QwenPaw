"""Model catalog authorization must fail closed and never export credentials."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole


def actor(role=PlatformRole.MEMBER):
    return ActorContext(uuid4(), ActorType.USER, role, False, "test")


class Repository:
    def __init__(self):
        self.enforced = True
        self.rows = []
        self.allowed = set()

    async def get_status(self):
        return {"enforced": self.enforced, "version": 0}

    async def list_models(self):
        return self.rows

    async def allowed_models(self, user_id, agent_id):
        return self.allowed if user_id == self.user_id else set()

    async def list_users(self):
        return [{"id": self.user_id, "username": "Alice"}]


class Manager:
    async def list_provider_info(self):
        from qwenpaw.providers.provider import ProviderInfo, ModelInfo

        return [
            ProviderInfo(
                id="fixture",
                name="Fixture",
                api_key="synthetic-secret",
                models=[
                    ModelInfo(
                        id="one",
                        name="One",
                        generate_kwargs={"secret": "synthetic-secret"},
                    )
                ],
            )
        ]

    def get_provider(self, provider_id):
        return (
            SimpleNamespace(has_model=lambda key: key == "one")
            if provider_id == "fixture"
            else None
        )


@pytest.mark.asyncio
async def test_user_grant_isolation_and_disabled_model_never_falls_back():
    from qwenpaw.models.governance import ModelGovernanceService, ModelAccessError

    repo, manager, user = Repository(), Manager(), actor()
    repo.user_id = user.user_id
    service = ModelGovernanceService(repo, manager)
    preview = await service.preview_import(actor(PlatformRole.ADMIN), manager)
    assert "synthetic-secret" not in str(preview)
    row = preview[0]
    repo.rows = [{**row, "status": "active", "provider_status": "active"}]
    repo.allowed = {row["id"]}
    assert len((await service.list_catalog(user, "agent"))["models"]) == 1
    assert (await service.list_catalog(actor(), "agent"))["models"] == []
    repo.rows[0]["status"] = "disabled"
    with pytest.raises(ModelAccessError):
        await service.require_model(user, "agent", "fixture", "one")
    repo.enforced = False
    with pytest.raises(ModelAccessError):
        await service.require_model(user, "agent", "fixture", "one")


@pytest.mark.asyncio
async def test_default_reference_blocks_deletion():
    from qwenpaw.models.runtime import require_no_model_references

    manager = Manager()
    manager.get_active_model = lambda: SimpleNamespace(
        provider_id="fixture", model="one"
    )
    with pytest.raises(ValueError, match="model_in_use"):
        await require_no_model_references(manager, "fixture", "one")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_id", "model_key"),
    [
        ("fixture", None),
        ("fixture", "one"),
        ("qwenpaw-local", "local-one"),
    ],
)
async def test_legacy_conversation_override_blocks_model_deletion(
    monkeypatch,
    tmp_path,
    provider_id,
    model_key,
):
    from qwenpaw.app.chats.models import ChatSpec, ChatsFile
    from qwenpaw.app.chats.repo import JsonChatRepository
    from qwenpaw.models import runtime

    selected_model = model_key or "one"
    workspace = tmp_path / "agent"
    repo = JsonChatRepository(workspace / "chats.json")
    await repo.save(
        ChatsFile(
            chats=[
                ChatSpec(
                    session_id="console:user",
                    user_id="user",
                    meta={
                        "model_override": {
                            "provider_id": provider_id,
                            "model": selected_model,
                        }
                    },
                )
            ]
        )
    )
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "agent": SimpleNamespace(workspace_dir=str(workspace)),
            }
        )
    )
    manager = Manager()
    manager.get_active_model = lambda: None
    monkeypatch.setattr(runtime, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr("qwenpaw.config.utils.load_config", lambda: config)
    monkeypatch.setattr(
        runtime,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(active_model=None),
    )

    with pytest.raises(ValueError, match="model_in_use: conversation_override"):
        await runtime.require_no_model_references(manager, provider_id, model_key)


@pytest.mark.asyncio
async def test_legacy_model_deletion_allows_complete_scan_without_references(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.chats.models import ChatSpec, ChatsFile
    from qwenpaw.app.chats.repo import JsonChatRepository
    from qwenpaw.models import runtime

    workspace = tmp_path / "agent"
    await JsonChatRepository(workspace / "chats.json").save(
        ChatsFile(
            chats=[ChatSpec(session_id="console:user", user_id="user")],
        )
    )
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"agent": SimpleNamespace(workspace_dir=str(workspace))}
        )
    )
    manager = Manager()
    manager.get_active_model = lambda: None
    monkeypatch.setattr(runtime, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr("qwenpaw.config.utils.load_config", lambda: config)
    monkeypatch.setattr(
        runtime,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(active_model=None),
    )

    await runtime.require_no_model_references(manager, "fixture", "one")


@pytest.mark.asyncio
async def test_legacy_model_deletion_fails_closed_when_chat_scan_is_unreadable(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.models import runtime

    workspace = tmp_path / "agent"
    workspace.mkdir()
    (workspace / "chats.json").write_text("not-json", encoding="utf-8")
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"agent": SimpleNamespace(workspace_dir=str(workspace))}
        )
    )
    manager = Manager()
    manager.get_active_model = lambda: None
    monkeypatch.setattr(runtime, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr("qwenpaw.config.utils.load_config", lambda: config)
    monkeypatch.setattr(
        runtime,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(active_model=None),
    )

    with pytest.raises(ValueError, match="model_reference_authority_unavailable"):
        await runtime.require_no_model_references(manager, "fixture", "one")


@pytest.mark.asyncio
async def test_enforcement_preview_reports_uncovered_users():
    from qwenpaw.models.governance import ModelGovernanceService

    repo = Repository()
    repo.user_id = uuid4()
    result = await ModelGovernanceService(repo, Manager()).preview_enforcement(
        actor(PlatformRole.ADMIN), []
    )
    assert result["uncovered_users"][0]["username"] == "Alice"


@pytest.mark.asyncio
async def test_database_failure_does_not_enable_compatibility():
    from qwenpaw.models.governance import ModelGovernanceService

    class Broken(Repository):
        async def get_status(self):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await ModelGovernanceService(Broken(), Manager()).list_catalog(actor(), "agent")


@pytest.mark.asyncio
async def test_import_preview_requires_admin_and_has_stable_keys():
    from qwenpaw.models.governance import ModelGovernanceService
    from qwenpaw.access.service import AuthorizationDeniedError
    from uuid import NAMESPACE_URL, uuid5

    service = ModelGovernanceService(Repository(), Manager())
    with pytest.raises(AuthorizationDeniedError):
        await service.preview_import(actor(), Manager())
    rows = await service.preview_import(actor(PlatformRole.ADMIN), Manager())
    assert rows[0]["id"] == str(
        uuid5(uuid5(NAMESPACE_URL, "qwenpaw:model-provider:fixture"), "one")
    )
