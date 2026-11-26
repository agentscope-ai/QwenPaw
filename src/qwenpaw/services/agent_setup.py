# -*- coding: utf-8 -*-
"""Workspace preparation and persistent registration for local agents.

Callers choose the agent ID, defaults and template. These operations create
workspace assets and register the resulting profile without starting an agent.
"""

import json
import logging
from pathlib import Path
from typing import Any

from ..agents.utils import copy_workspace_md_files
from ..agents.skill_system import SkillPoolService, get_workspace_skills_dir
from ..config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    save_agent_mail_credentials,
)
from ..config.utils import mutate_config
from ..utils.io_utils import write_json_atomic
from ..utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)


def normalized_agent_order(config) -> list[str]:
    """Return a deduplicated agent order covering every configured agent."""
    profile_ids = list(config.agents.profiles.keys())
    ordered_ids: list[str] = []

    for agent_id in config.agents.agent_order:
        if agent_id in config.agents.profiles and agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    for agent_id in profile_ids:
        if agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    return ordered_ids


def register_agent(
    agent_id: str,
    agent_ref: AgentProfileRef,
    agent_config: AgentProfileConfig,
) -> None:
    """Register a new agent under the root-config transaction lock."""

    def apply_registration(config: Any) -> None:
        if agent_id in config.agents.profiles:
            raise ValueError(f"Agent ID '{agent_id}' already exists")
        agent_path = Path(agent_ref.workspace_dir).expanduser() / "agent.json"
        if agent_config.mail is not None:
            save_agent_mail_credentials(agent_path.parent, agent_config.mail)
        write_json_atomic(
            agent_path,
            agent_config.model_dump(exclude_none=True),
        )
        config.agents.profiles[agent_id] = agent_ref
        config.agents.agent_order = normalized_agent_order(config)

    mutate_config(apply_registration)


def _apply_workspace_md_templates(
    workspace_dir: Path,
    language: str,
    *,
    md_template_id: str | None,
) -> None:
    """Copy common and template-specific markdown files for a workspace."""
    copy_workspace_md_files(
        language,
        workspace_dir,
        md_template_id=md_template_id,
    )


def _ensure_heartbeat_file(workspace_dir: Path, language: str) -> None:
    """Create the default HEARTBEAT.md if it is missing."""
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if heartbeat_file.exists():
        return

    default_heartbeat_mds = {
        "zh": """# Heartbeat checklist
- 扫描收件箱紧急邮件
- 查看未来 2h 的日历
- 检查待办是否卡住
- 若安静超过 8h，轻量 check-in
""",
        "en": """# Heartbeat checklist
- Scan inbox for urgent email
- Check calendar for next 2h
- Check tasks for blockers
- Light check-in if quiet for 8h
""",
        "ru": """# Heartbeat checklist
- Проверить входящие на срочные письма
- Просмотреть календарь на ближайшие 2 часа
- Проверить задачи на наличие блокировок
- Лёгкая проверка при отсутствии активности более 8 часов
""",
    }
    heartbeat_content = default_heartbeat_mds.get(
        language,
        default_heartbeat_mds["en"],
    )
    with open(heartbeat_file, "w", encoding="utf-8") as file:
        file.write(heartbeat_content.strip())


def _install_initial_skills(
    workspace_dir: Path,
    skill_names: list[str] | None,
) -> None:
    """Install requested initial skills from the skill pool."""
    if not skill_names:
        return

    pool_service = SkillPoolService()
    for skill_name in skill_names:
        try:
            result = pool_service.download_to_workspace(
                skill_name=skill_name,
                workspace_dir=workspace_dir,
                overwrite=False,
            )
            if result.get("success"):
                continue
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                sanitize_log_value(skill_name),
                sanitize_log_value(workspace_dir),
                sanitize_log_value(result.get("reason", "unknown")),
            )
        except Exception as e:
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                sanitize_log_value(skill_name),
                sanitize_log_value(workspace_dir),
                sanitize_log_value(e),
            )


def initialize_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str] | None = None,
    md_template_id: str | None = None,
    language: str | None = None,
    *,
    apply_md_templates: bool = True,
    create_skills_dir: bool = True,
    create_jobs_file: bool = True,
) -> None:
    """Initialize agent workspace with only explicitly requested skills."""
    from ..config import load_config as load_global_config

    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    if create_skills_dir:
        get_workspace_skills_dir(workspace_dir).mkdir(exist_ok=True)

    config = load_global_config()
    if not language:
        language = config.agents.language or "zh"

    if apply_md_templates:
        _apply_workspace_md_templates(
            workspace_dir,
            language,
            md_template_id=md_template_id,
        )
        _ensure_heartbeat_file(workspace_dir, language)
    _install_initial_skills(workspace_dir, skill_names)

    if create_jobs_file:
        jobs_file = workspace_dir / "jobs.json"
        if not jobs_file.exists():
            with open(jobs_file, "w", encoding="utf-8") as file:
                json.dump(
                    {"version": 1, "jobs": []},
                    file,
                    ensure_ascii=False,
                    indent=2,
                )

    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as file:
            json.dump(
                {"version": 1, "chats": []},
                file,
                ensure_ascii=False,
                indent=2,
            )
