# -*- coding: utf-8 -*-
"""Trigger logic for proactive conversation feature."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Any

from .proactive_types import ProactiveConfig
from .proactive_responder import (
    deliver_proactive_round,
    last_inbox_push_at,
    load_proactive_settings,
)
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


# Store workspace references to avoid creating duplicate Workspaces
proactive_workspaces: Dict[str, Any] = {}


def enable_proactive_for_session(
    session_id: str,
    idle_minutes: int = 30,
    workspace: Optional["Workspace"] = None,
) -> str:
    """Enable proactive for the given session and start monitoring.

    Args:
        session_id: Session identifier.
        idle_minutes: Idle threshold in minutes before triggering proactive.
        workspace: Current running Workspace to reuse. Must be provided
            to avoid creating duplicate Workspace instances.
    """
    if workspace is None:
        raise ValueError(
            "workspace must be provided to enable_proactive_for_session. "
            "Pass the current HookContext.workspace from the command handler.",
        )

    # Store the workspace reference for the trigger loop to use
    proactive_workspaces[session_id] = workspace

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


async def disable_proactive_for_session(
    session_id: str,
) -> str:
    """Disable proactive for the given session and clean up resources.

    Cancels the background trigger loop task, removes the session
    entry from both ``proactive_tasks`` and ``proactive_configs``,
    and returns a human-readable confirmation message.
    """
    # Cancel the running task if it exists
    if session_id in proactive_tasks:
        task = proactive_tasks[session_id]
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        del proactive_tasks[session_id]

    # Remove config to free memory and signal the loop to exit
    proactive_configs.pop(session_id, None)

    # Clean up workspace reference
    proactive_workspaces.pop(session_id, None)

    return "Proactive mode disabled."


async def _run_trigger_loop(
    session_id: str,
) -> None:
    """Internal function to run the trigger loop."""
    try:
        await proactive_trigger_loop(session_id)
    except Exception as e:
        logger.error(f"Error in proactive trigger: {e}")


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


async def _delivered_recently(workspace: Any, settings: Any) -> bool:
    """Whether an inbox push already happened inside the refresh window.

    Replaces the old "last chat message was ``[PROACTIVE]``" guard: the
    agenda is no longer written into a chat, so the delivery ledger is the
    only honest record of what the user already saw.
    """
    window = int(settings.refresh_min_interval_minutes)
    if window <= 0:
        return False
    last = await last_inbox_push_at(str(workspace.workspace_dir), settings)
    if last is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed < window * 60


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

    # Defensive None checks: both stamps are set by
    # ``enable_proactive_for_session`` and refreshed by the loop, so a
    # missing value means the session state was reset underneath us.
    if (
        config.last_user_interaction is None
        or config.mode_enabled_time is None
    ):
        return last_trigger_attempt

    settings = await load_proactive_settings(workspace.agent_id)
    if not settings.enabled:
        logger.info(
            "Proactive agenda disabled in config; skipping idle round",
        )
        return last_trigger_attempt

    if await _delivered_recently(workspace, settings):
        logger.info("Recent proactive inbox push; skipping idle round")
        return now_utc

    logger.info("Triggering proactive agenda delivery now")

    # Update attempt time
    new_attempt_time = now_utc
    config.running_task_id = f"proactive_{now_utc.timestamp()}"

    try:
        outcome = await deliver_proactive_round(
            agent_id=workspace.agent_id,
            workspace_dir=str(workspace.workspace_dir),
            memory_manager=workspace.memory_manager,
            channel="idle",
            settings=settings,
        )
        logger.info(
            "Proactive idle round done for %s: shown=%d pushed=%s "
            "reason=%s",
            session_id,
            len(outcome.shown),
            outcome.pushed,
            outcome.skip_reason or "-",
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

    # Get the workspace that was stored when proactive was enabled
    workspace = proactive_workspaces.get(session_id)
    if workspace is None:
        logger.error(
            "No workspace found for session %s in proactive_workspaces. "
            "Proactive was likely enabled without passing a workspace.",
            session_id,
        )
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
