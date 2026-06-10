# -*- coding: utf-8 -*-
"""Trigger logic for proactive conversation feature."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Any

from .proactive_types import ProactiveConfig
from .proactive_responder import generate_proactive_response
from .proactive_utils import (
    get_last_message_ts,
    ensure_tz_aware,
    is_agent_busy,
)

if TYPE_CHECKING:
    from ....app.workspace import Workspace

logger = logging.getLogger(__name__)

# Global storage for proactive configurations per session
proactive_configs: Dict[str, ProactiveConfig] = {}
proactive_tasks: Dict[str, asyncio.Task] = {}


def enable_proactive_for_session(
    session_id: str,
    idle_minutes: int = 30,
) -> str:
    """Enable proactive for the given session and start monitoring."""
    # Removed unused global declaration.
    # We are only writing to the dict, not reassigning the variable itself.

    config = ProactiveConfig(
        enabled=True,
        idle_minutes=idle_minutes,
        last_user_interaction=datetime.now(timezone.utc),
        mode_enabled_time=datetime.now(timezone.utc),
    )
    proactive_configs[session_id] = config

    # Start the proactive trigger loop if not already running
    if session_id not in proactive_tasks or proactive_tasks[session_id].done():
        task = asyncio.create_task(_run_trigger_loop(session_id))
        proactive_tasks[session_id] = task

    return f"Proactive mode enabled with {idle_minutes} minute idle threshold."


async def _run_trigger_loop(
    session_id: str,
) -> None:
    """Internal function to run the trigger loop."""
    try:
        await proactive_trigger_loop(session_id)
    except Exception as e:
        logger.error(f"Error in proactive trigger: {e}")


async def is_last_message_proactive(workspace: Any) -> bool:
    """Check if the last message in session was a proactive message."""
    from agentscope.memory import InMemoryMemory
    from ....app.runner.utils import agentscope_msg_to_message

    try:
        chats = await workspace.chat_manager.list_chats()

        # Find the most recently updated session
        sessions_with_ts = [(ensure_tz_aware(s.updated_at), s) for s in chats]
        _, latest_session = max(sessions_with_ts)

        session_id = latest_session.session_id
        user_id = latest_session.user_id
        channel = latest_session.channel

        state = await workspace.runner.session.get_session_state_dict(
            session_id,
            user_id,
            channel,
        )

        memories_data = state.get("agent", {}).get("memory", [])

        memory = InMemoryMemory()
        memory.load_state_dict(memories_data)
        messages = await memory.get_memory()

        serializable_messages = agentscope_msg_to_message(messages)

        latest_msg = serializable_messages[-1]
        contents = getattr(latest_msg, "contents", [])

        if not contents or not isinstance(contents, list):
            return "[PROACTIVE]" in str(latest_msg)

        for content_item in contents:
            text_content = ""
            if hasattr(content_item, "text"):
                text_content = content_item.text

            if "[PROACTIVE]" in text_content:
                return True

        return False

    except Exception as e:
        logger.warning(f"Could not check if last message was proactive: {e}")
        return False


def _should_trigger_proactive(
    config: ProactiveConfig,
    last_interaction_tz_aware: datetime,
    current_time: datetime,
) -> bool:
    """Determine if proactive trigger conditions are met."""
    elapsed_time = current_time - last_interaction_tz_aware
    elapsed_minutes = elapsed_time.total_seconds() / 60.0

    if elapsed_minutes < config.idle_minutes:
        return False

    if not config.mode_enabled_time:
        return True

    mode_enabled_time_tz_aware = ensure_tz_aware(config.mode_enabled_time)
    time_since_mode_enabled = (
        current_time - mode_enabled_time_tz_aware
    ).total_seconds() / 60.0

    return time_since_mode_enabled >= config.idle_minutes


async def _handle_proactive_trigger(
    session_id: str,
    config: ProactiveConfig,
    last_trigger_attempt: Optional[datetime],
    workspace: "Workspace",
) -> Optional[datetime]:
    """Handle the logic when a proactive trigger is attempted."""
    now_utc = datetime.now(timezone.utc)

    # Check cooldown and running task status
    if config.running_task_id is not None:
        return last_trigger_attempt

    if last_trigger_attempt is not None:
        time_since_last_attempt = (
            now_utc - ensure_tz_aware(last_trigger_attempt)
        ).total_seconds()
        if time_since_last_attempt <= 60:
            return last_trigger_attempt

    # Check if last message is already proactive
    # Added None checks to satisfy MyPy and ensure logic correctness
    if config.last_user_interaction is None:
        return last_trigger_attempt

    last_interaction_tz_aware = ensure_tz_aware(config.last_user_interaction)

    if config.mode_enabled_time is None:
        return last_trigger_attempt

    mode_enabled_time_tz_aware = ensure_tz_aware(config.mode_enabled_time)

    last_interaction_was_before_mode_enabled = (
        last_interaction_tz_aware <= mode_enabled_time_tz_aware
    )

    if not last_interaction_was_before_mode_enabled:
        if await is_last_message_proactive(workspace):
            logger.info("Last Proactive Message Unresponded, skipping")
            return now_utc

    logger.info("Triggering proactive response now")

    # Update attempt time
    new_attempt_time = now_utc
    config.running_task_id = f"proactive_{now_utc.timestamp()}"

    try:
        responder_task = asyncio.create_task(
            generate_proactive_response(workspace),
        )

        proactive_msg = await responder_task

        if proactive_msg:
            msg_preview = str(proactive_msg)[:100]
            logger.info(
                f"Proactive message generated for session {session_id}: "
                f"{msg_preview}...",
            )

    except Exception as e:
        logger.error(f"Error in proactive responder: {e}")
    finally:
        if session_id in proactive_configs:
            proactive_configs[session_id].running_task_id = None

    return new_attempt_time


async def proactive_trigger_loop(
    session_id: str,
) -> None:
    """Background loop that polls every 30s to detect idle periods."""
    # Removed unused global declaration. Only reading from dict.

    last_trigger_attempt: Optional[datetime] = None

    try:
        from ....app.agent_context import get_current_agent_id
        from ....app.multi_agent_manager import MultiAgentManager

        active_agent_id = get_current_agent_id()
        multi_agent_manager = MultiAgentManager()
        workspace = await multi_agent_manager.get_agent(active_agent_id)
    except Exception as e:
        logger.error(f"Failed to initialize workspace for proactive loop: {e}")
        return

    while True:
        try:
            await asyncio.sleep(30)

            if session_id not in proactive_configs:
                continue

            config = proactive_configs[session_id]
            if not config.enabled:
                continue

            if await is_agent_busy(workspace):
                continue

            actual_last_user_time = await get_last_message_ts(
                workspace=workspace,
            )

            if actual_last_user_time is not None:
                # Fix: Always use UTC when converting timestamp
                last_interaction_dt = datetime.fromtimestamp(
                    actual_last_user_time,
                    tz=timezone.utc,
                )
            else:
                last_interaction_dt = config.last_user_interaction

            if last_interaction_dt is None:
                continue

            last_interaction_tz_aware = ensure_tz_aware(last_interaction_dt)
            current_time = datetime.now(timezone.utc)

            if not _should_trigger_proactive(
                config,
                last_interaction_tz_aware,
                current_time,
            ):
                continue

            # Attempt to trigger
            config.last_user_interaction = last_interaction_tz_aware

            last_trigger_attempt = await _handle_proactive_trigger(
                session_id,
                config,
                last_trigger_attempt,
                workspace,
            )

        except asyncio.CancelledError:
            logger.info("Proactive trigger loop cancelled")
            break
        except Exception as e:
            logger.error(f"Error in proactive trigger loop: {e}")
