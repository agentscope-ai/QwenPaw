# -*- coding: utf-8 -*-
"""Service factory functions for workspace components.

Factory functions are used by Workspace._register_services() to create
and initialize service components. Extracted from local functions to
improve testability and code organization.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from ...utils.io_utils import run_sync_io

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


async def create_driver_service(
    ws: "Workspace",
    _service,
    publish: Callable[[Any], None],
):
    """Publish lightweight storage before starting available sources."""
    # pylint: disable=protected-access
    from ..driver_runtime_service import LazyDriverService
    from ..mail.driver_config import (
        is_managed_qwenpawmail_card,
        sync_qwenpawmail_driver_card,
    )

    service = LazyDriverService(ws)
    publish(service)
    # Upgrade legacy qwenpawmail cards before DriverManager can launch them.
    # ``load_agent_config`` has already hydrated the in-memory secrets from the
    # encrypted store at this point.
    mail = getattr(ws._config, "mail", None)
    existing_mail_card = (
        ws.workspace_dir / "drivers" / "mcp" / "qwenpawmail.yaml"
    )
    should_sync_mail_card = mail is not None or await asyncio.to_thread(
        is_managed_qwenpawmail_card,
        existing_mail_card,
    )
    if should_sync_mail_card and not await asyncio.to_thread(
        sync_qwenpawmail_driver_card,
        ws.workspace_dir,
        mail,
        getattr(ws._config, "backend", "qwenpaw"),
    ):
        logger.warning(
            "qwenpawmail DriverCard could not be synchronized for agent %s; "
            "mail capability remains disabled",
            ws.agent_id,
        )

    await service.start()
    return service


async def create_driver_config_watcher(ws, _service, publish):
    """Compatibility factory; the lazy service owns watcher lifecycle."""
    # pylint: disable=protected-access
    service = ws._service_manager.services.get("driver_manager")
    watcher = service.watcher if service is not None else None
    if watcher is not None:
        publish(watcher)
    return watcher


async def create_chat_service(
    ws: "Workspace",
    service,
    publish: Callable[[Any], None],
):
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

    async def close_browser_session(session_id: str) -> None:
        await get_default_kernel_manager().close_session(
            derive_workspace_id(ws.workspace_dir),
            session_id,
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
        )
        publish(cm)
        logger.info(f"ChatManager created: {chats_path}")
    cm.set_on_session_closed(close_browser_session)

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


async def create_channel_service(
    ws: "Workspace",
    _,
    publish: Callable[[Any], None],
):
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

    async def on_last_dispatch(channel, user_id, session_id):
        await run_sync_io(
            update_last_dispatch,
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            agent_id=ws.agent_id,
        )

    def process(request, *args, **kwargs):
        """Resolve the current entrypoint without wrapping its iterator."""
        return ws.stream_query(request, *args, **kwargs)

    cm = ChannelManager.from_config(
        process=process,
        config=temp_config,
        on_last_dispatch=on_last_dispatch,
        workspace_dir=ws.workspace_dir,
    )
    publish(cm)

    cm.set_workspace(ws)
    from ..approvals import get_approval_service

    get_approval_service().set_channel_manager(cm, agent_id=ws.agent_id)

    agent_language = getattr(ws._config, "language", "zh") or "zh"
    for ch in cm.channels:
        ch._language = agent_language

    return cm
    # pylint: enable=protected-access


async def create_mail_monitor_service(
    ws: "Workspace",
    _,
    publish: Callable[[Any], None],
):
    """Create the mail push monitor when enabled for this agent.

    Started only when the agent has a personal mailbox with credentials
    and ``mail.push.mode != "off"``.  Dedicated new mailboxes
    (is_new_account=True, no auth_code yet) never start the monitor.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        MailMonitorService instance or None if not enabled
    """
    # pylint: disable=protected-access
    # Mail push is only supported for the qwenpaw backend: third-party
    # harness runtimes cannot handle the dict wake requests built by the
    # monitor and would fail on every incoming email.
    if getattr(ws._config, "backend", "qwenpaw") != "qwenpaw":
        return None
    mail = getattr(ws._config, "mail", None)
    if mail is None or mail.push is None or mail.push.mode == "off":
        return None
    if mail.is_new_account:
        return None
    credential = mail.credential
    if not credential.name or not credential.auth_code:
        return None

    from ..mail.monitor import MailMonitorService
    from ...agents.utils import ensure_workspace_md_file

    # The mail wake prompt asks the agent to read CONTACTS.md and
    # MAIL_TRIAGE.md first thing, so make sure both seed files exist
    # for workspaces created before these templates were introduced
    # (agent CRUD APIs are the only other distribution path).
    language = getattr(ws._config, "language", None)
    if not language:
        try:
            from ...config import load_config as _load_root_config

            language = _load_root_config().agents.language
        except Exception:  # pragma: no cover - config load best-effort
            language = None
    for seed_name in ("CONTACTS.md", "MAIL_TRIAGE.md"):
        ensure_workspace_md_file(ws.workspace_dir, language or "en", seed_name)

    monitor = MailMonitorService(
        agent_id=ws.agent_id,
        workspace=ws,
        mail_config=mail,
    )
    publish(monitor)
    return monitor
    # pylint: enable=protected-access


async def create_agent_config_watcher(
    ws: "Workspace",
    _,
    publish: Callable[[Any], None],
):
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
    publish(watcher)
    return watcher
    # pylint: enable=protected-access
