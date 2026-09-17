# -*- coding: utf-8 -*-
"""Service factory functions for workspace components.

Factory functions are used by Workspace._register_services() to create
and initialize service components. Extracted from local functions to
improve testability and code organization.
"""

from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


async def create_driver_service(ws: "Workspace", _service):
    """Create and initialize the per-workspace DriverManager.

    DriverManager is the runtime for external capabilities.  MCP is wired as
    the first concrete Driver protocol; legacy MCP config is migrated into
    DriverCard storage and is not exposed through the old MCP runtime path.
    """
    # pylint: disable=protected-access
    from ...drivers.adapters.mcp_legacy_config import (
        migrate_legacy_mcp_if_needed,
    )
    from ...drivers.credentials.store import AsyncCredentialStore
    from ...drivers.handlers import MCPDriverHandler
    from ...drivers.handlers.mcp import validate_mcp_endpoint
    from ...drivers.manager import DriverManager
    from ..approvals.driver_gate import QwenPawDriverApprovalGate

    credential_store = AsyncCredentialStore(ws.workspace_dir / "credentials.yaml")
    postgres_repository = None
    from ...identity.runtime import get_identity_schema
    from ..mcp.postgres_repository import (
        PostgresMCPRepository,
        is_postgres_mcp_enabled,
        workspace_uses_postgres,
    )
    from ..mcp.scoped_credentials import ScopedPostgresMCPCredentialStore

    if is_postgres_mcp_enabled():
        repository = PostgresMCPRepository(schema=get_identity_schema())
        if await workspace_uses_postgres(ws, repository=repository):
            postgres_repository = repository
            credential_store = ScopedPostgresMCPCredentialStore(
                agent_key=ws.agent_id,
                repository=repository,
            )
    from ..mcp.postgres_card_store import PostgresMCPCardStore

    driver_manager = DriverManager(
        ws.workspace_dir / "drivers",
        credential_store,
        approval_gate=QwenPawDriverApprovalGate(),
        card_store=(
            PostgresMCPCardStore(
                ws.workspace_dir / "drivers",
                agent_key=ws.agent_id,
                repository=postgres_repository,
            )
            if postgres_repository is not None
            else None
        ),
    )
    driver_manager.register_handler_type(
        "mcp",
        MCPDriverHandler,
        endpoint_validator=validate_mcp_endpoint,
    )
    # Future Driver protocols should be registered here together with their
    # endpoint validator and tests.  This PR intentionally keeps the concrete
    # runtime surface to MCP while leaving DriverManager protocol-neutral.
    if postgres_repository is None:
        await migrate_legacy_mcp_if_needed(ws, driver_manager)
    await driver_manager.start()
    ws._service_manager.services["driver_manager"] = driver_manager
    logger.debug(
        "DriverManager external capability runtime initialized for agent: %s",
        ws.agent_id,
    )
    return driver_manager
    # pylint: enable=protected-access


async def create_driver_config_watcher(ws: "Workspace", _service):
    """Create watcher for manual DriverCard edits.

    Console/API updates call ``DriverConfigService.reload_driver_best_effort``
    immediately.  This watcher covers the manual-edit path and works for all
    Driver protocols instead of only MCP.
    """
    # pylint: disable=protected-access
    driver_manager = ws._service_manager.services.get("driver_manager")
    if driver_manager is None:
        return None
    from ..mcp.scoped_credentials import ScopedPostgresMCPCredentialStore

    if isinstance(driver_manager.credential_store, ScopedPostgresMCPCredentialStore):
        return None

    from ..driver_config_watcher import DriverConfigWatcher

    watcher = DriverConfigWatcher(
        driver_manager,
        ws.workspace_dir / "drivers",
    )
    ws._service_manager.services["driver_config_watcher"] = watcher
    return watcher
    # pylint: enable=protected-access


async def create_chat_service(ws: "Workspace", service):
    """Create chat manager, or reuse existing one.

    Args:
        ws: Workspace instance
        service: Existing ChatManager if reused, None if creating new
    """
    # pylint: disable=protected-access
    from ..chats.manager import ChatManager
    from ..chats.repo.json_repo import JsonChatRepository
    from ...browser.runtime.links import link_for
    from ...browser.execution.kernel import get_default_kernel_manager
    from ...browser.tool_entrypoint import derive_workspace_id
    from uuid import UUID
    from ...access.agent_repository import (
        PostgresAgentRepository,
        agent_database_id,
    )
    from ..chats.repo import PostgresConversationRepository
    from ..chats.run_persistence import PostgresChatRunPersistence
    from ..chats.backfill import backfill_agent_chats, register_chat_metadata
    from ...identity.runtime import get_identity_schema, is_multi_user_enabled
    from datetime import datetime, timezone

    async def close_browser_session(session_id: str) -> None:
        await get_default_kernel_manager().close_session(
            derive_workspace_id(ws.workspace_dir),
            session_id,
        )

    agent_repository = None
    conversation_repository = None
    agent_owner_user_id = None
    if is_multi_user_enabled():
        agent_repository = PostgresAgentRepository(
            schema=get_identity_schema(),
        )
        conversation_repository = PostgresConversationRepository(
            schema=get_identity_schema(),
        )
        governance = await agent_repository.get_governance(agent_key=ws.agent_id)
        agent_owner_user_id = (
            governance.owner_user_id if governance is not None else None
        )

    async def record_chat_created(chat) -> None:
        if not is_multi_user_enabled():
            return
        try:
            user_id = UUID(chat.user_id)
        except (TypeError, ValueError):
            return
        if conversation_repository is None or agent_repository is None:
            raise RuntimeError("conversation_repository_unavailable")
        await register_chat_metadata(
            chat=chat,
            agent_id=agent_database_id(ws.agent_id),
            repository=conversation_repository,
        )
        await agent_repository.record_chat_created(
            agent_key=ws.agent_id,
            user_id=user_id,
            created_at=chat.created_at,
        )

    async def record_chats_deleted(chats) -> None:
        if not is_multi_user_enabled():
            return
        if conversation_repository is None:
            raise RuntimeError("conversation_repository_unavailable")
        deleted_at = datetime.now(timezone.utc)
        for chat in chats:
            try:
                conversation_id = UUID(chat.id)
            except (TypeError, ValueError):
                continue
            try:
                owner_user_id = UUID(chat.user_id)
            except (TypeError, ValueError):
                if agent_owner_user_id is None:
                    raise RuntimeError("conversation_owner_unavailable")
                owner_user_id = agent_owner_user_id
            updated = await conversation_repository.with_user(
                owner_user_id,
            ).update_conversation(
                conversation_id,
                status="deleted",
                updated_at=deleted_at,
            )
            if updated is None:
                raise RuntimeError("conversation_delete_sync_failed")

    run_persistence = None
    if is_multi_user_enabled():
        run_persistence = PostgresChatRunPersistence(
            repository=conversation_repository,
            agent_id=agent_database_id(ws.agent_id),
            payload_storage_dir=(ws.workspace_dir / ".qwenpaw" / "chat-event-payloads"),
        )

    if service is not None:
        cm = service
        logger.info(f"Reusing ChatManager for {ws.agent_id}")
    else:
        chats_path = str(ws.workspace_dir / "chats.json")
        chat_repo = JsonChatRepository(chats_path)
        cm = ChatManager(
            repo=chat_repo,
            on_session_closed=close_browser_session,
            on_chat_created=record_chat_created,
            on_chats_deleted=record_chats_deleted,
            run_persistence=run_persistence,
            conversation_repository=conversation_repository,
        )
        ws._service_manager.services["chat_manager"] = cm
        logger.info(f"ChatManager created: {chats_path}")
    cm.set_on_session_closed(close_browser_session)
    cm.set_on_chat_created(record_chat_created)
    cm.set_on_chats_deleted(record_chats_deleted)
    cm.set_run_persistence(run_persistence)
    cm.set_conversation_repository(conversation_repository)

    if is_multi_user_enabled() and conversation_repository is not None:
        existing_chats = await cm.list_chats()
        report = await backfill_agent_chats(
            chats=existing_chats,
            agent_id=agent_database_id(ws.agent_id),
            agent_owner_user_id=agent_owner_user_id,
            repository=conversation_repository,
        )
        logger.info(
            "Conversation metadata backfill for %s: scanned=%s inserted=%s "
            "updated=%s skipped=%s ambiguous=%s",
            ws.agent_id,
            report.scanned,
            report.inserted,
            report.updated,
            report.skipped,
            report.ambiguous,
        )

    async def live_session_ids() -> set[str]:
        chats = await cm.list_chats(archived=False)
        return {chat.session_id for chat in chats}

    chrome_link = link_for("chrome")
    register_resolver = getattr(
        chrome_link,
        "register_live_session_resolver",
        None,
    )
    if register_resolver is not None:
        register_resolver(
            derive_workspace_id(ws.workspace_dir),
            live_session_ids,
        )
    # pylint: enable=protected-access


async def create_channel_service(ws: "Workspace", _):
    """Create channel manager if configured.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        ChannelManager instance or None if not configured
    """
    # pylint: disable=protected-access
    if not ws._config.channels:
        return None

    from ...config import Config, load_config, update_last_dispatch
    from ..channels.manager import ChannelManager
    from ..channels.access_control import init_access_control_store

    init_access_control_store(ws.workspace_dir)

    root_config = load_config()
    temp_config = Config(
        channels=ws._config.channels,
        show_tool_details=root_config.show_tool_details,
    )

    def on_last_dispatch(channel, user_id, session_id):
        platform_user_id = None
        if channel == "console":
            try:
                from uuid import UUID

                platform_user_id = str(UUID(str(user_id)))
            except ValueError:
                platform_user_id = None
        update_last_dispatch(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            agent_id=ws.agent_id,
            platform_user_id=platform_user_id,
        )

    cm = ChannelManager.from_config(
        process=ws.stream_query,
        config=temp_config,
        on_last_dispatch=on_last_dispatch,
        workspace_dir=ws.workspace_dir,
    )
    ws._service_manager.services["channel_manager"] = cm

    cm.set_workspace(ws)
    from ..approvals import get_approval_service

    get_approval_service().set_channel_manager(cm, agent_id=ws.agent_id)

    agent_language = getattr(ws._config, "language", "zh") or "zh"
    for ch in cm.channels:
        ch._language = agent_language

    return cm
    # pylint: enable=protected-access


async def create_agent_config_watcher(ws: "Workspace", _):
    """Create agent config watcher if channel/cron exists.

    The watcher only triggers reloads via ``MultiAgentManager`` and
    does not need direct references to channel/cron managers anymore.
    Creation is still gated on having at least one of them, since
    workspaces with neither have no externally-visible state that
    benefits from auto-reload.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        AgentConfigWatcher instance or None if not needed
    """
    # pylint: disable=protected-access
    channel_mgr = ws._service_manager.services.get("channel_manager")
    cron_mgr = ws._service_manager.services.get("cron_manager")

    if not (channel_mgr or cron_mgr):
        return None

    from ..agent_config_watcher import AgentConfigWatcher

    watcher = AgentConfigWatcher(
        agent_id=ws.agent_id,
        workspace_dir=ws.workspace_dir,
        workspace=ws,
    )
    ws._service_manager.services["agent_config_watcher"] = watcher
    return watcher
    # pylint: enable=protected-access
