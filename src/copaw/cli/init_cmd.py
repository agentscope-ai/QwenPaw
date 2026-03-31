# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""CLI init: interactively create working_dir config.json and HEARTBEAT.md."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from .channels_cmd import configure_channels_interactive
from .env_cmd import configure_env_interactive
from .providers_cmd import configure_providers_interactive
from .skills_cmd import configure_skills_interactive
from .utils import prompt_confirm, prompt_choice
from ..config import (
    get_config_path,
    get_heartbeat_query_path,
    load_config,
    save_config,
)
from ..config.config import (
    ActiveHoursConfig,
    Config,
    HeartbeatConfig,
)
from ..constant import HEARTBEAT_DEFAULT_EVERY
from ..providers import ProviderManager
from ..constant import WORKING_DIR

SECURITY_WARNING = """
Security warning — please read.

CoPaw is a personal assistant that runs in your own environment. It can connect to
channels (DingTalk, Feishu, QQ, Discord, iMessage, etc.) and run skills that read
files, run commands, and call external APIs. By default it is a single-operator
boundary: one trusted user. A malicious or confused prompt can lead the agent to
do unsafe things if tools are enabled.

If multiple people can message the same CoPaw instance with tools enabled, they
share the same delegated authority (files, commands, secrets the agent can use).

If you are not comfortable with access control and hardening, do not run CoPaw with
tools or expose it to untrusted users. Get help from someone experienced before
enabling powerful skills or exposing the bot to the internet.

Recommended baseline:
- Restrict which channels and users can trigger the agent; use allowlists where possible.
- Multi-user or shared inbox: use separate config/credentials and ideally separate
  OS users or hosts per trust boundary.
- Run skills with least privilege; sandbox where you can.
- Keep secrets out of the agent's working directory and skill-accessible paths.
- Use a capable model when the agent has tools or handles untrusted input.

Review your config and skills regularly; limit tool scope to what you need.
"""

TELEMETRY_INFO = """
Help improve CoPaw by sharing anonymous usage data!

We collect only:
• CoPaw version (e.g., 0.0.7)
• Install method (pip, Docker, or desktop app)
• OS and version (e.g., macOS 14.0, Ubuntu 22.04)
• Python version (e.g., 3.11)
• CPU architecture (e.g., x86_64, arm64)
• GPU availability (detected, not detailed specs)

No personal data collected! No files, no credentials, no identifiable information.
This helps us understand CoPaw's usage environment and prioritize improvements.
"""


def _echo_security_warning_box() -> None:
    """Print SECURITY_WARNING in a rich panel with blue border."""
    console = Console()
    console.print(
        Panel(
            SECURITY_WARNING.strip(),
            title="[bold]🐾 Security warning — please read[/bold]",
            border_style="blue",
        ),
    )


def _echo_telemetry_info_box() -> None:
    """Print TELEMETRY_INFO in a rich panel with blue border."""
    console = Console()
    console.print(
        Panel(
            TELEMETRY_INFO.strip(),
            title="[bold]📊 Help improve CoPaw[/bold]",
            border_style="blue",
        ),
    )


DEFAULT_HEARTBEAT_MDS = {
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


@click.command("init")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing config.json and HEARTBEAT.md if present.",
)
@click.option(
    "--defaults",
    "use_defaults",
    is_flag=True,
    help="Use defaults only, no interactive prompts (for scripts).",
)
@click.option(
    "--accept-security",
    "accept_security",
    is_flag=True,
    help="Skip security confirmation (use with --defaults for scripts/Docker).",
)
# pylint: disable=too-many-branches,too-many-statements
def init_cmd(
    force: bool,
    use_defaults: bool,
    accept_security: bool,
) -> None:
    """Create working dir with config.json and HEARTBEAT.md (interactive)."""
    from pathlib import Path
    from ..app.migration import (
        ensure_default_agent_exists,
        ensure_qa_agent_exists,
        migrate_legacy_skills_to_skill_pool,
    )

    config_path = get_config_path()
    working_dir = config_path.parent
    heartbeat_path = get_heartbeat_query_path()

    click.echo(f"Working dir: {working_dir}")

    # --- Security warning: must accept to continue ---
    _echo_security_warning_box()
    if use_defaults and accept_security:
        click.echo(
            "Security acceptance assumed (--accept-security with --defaults).",
        )
    else:
        accepted = prompt_confirm(
            "Have you read and accepted the security notice above? (yes to continue, no to abort)",
            default=True,
        )
        if not accepted:
            click.echo(
                "Initialization aborted. Read the security notice and run again when ready.",
            )
            raise click.Abort()
    working_dir.mkdir(parents=True, exist_ok=True)

    # --- Telemetry collection (optional, anonymous) ---
    from ..utils.telemetry import (
        collect_and_upload_telemetry,
        has_telemetry_been_collected,
        is_telemetry_opted_out,
        mark_telemetry_collected,
    )

    if not is_telemetry_opted_out(
        working_dir,
    ) and not has_telemetry_been_collected(working_dir):
        if use_defaults:
            success = collect_and_upload_telemetry(working_dir)

        else:
            _echo_telemetry_info_box()
            if prompt_confirm("Share usage data?", default=True):
                success = collect_and_upload_telemetry(working_dir)
                if success:
                    click.echo("✓ Thank you!")
            else:
                mark_telemetry_collected(working_dir, opted_out=True)

    # --- Ensure default agent workspace exists ---
    click.echo("\n=== Default Workspace Initialization ===")
    ensure_default_agent_exists()
    migrate_legacy_skills_to_skill_pool()
    click.echo("✓ Default workspace initialized")
    ensure_qa_agent_exists()
    click.echo("✓ Builtin QA agent workspace ensured")

    # --- Ensure local skill hub exists ---
    from ..agents.skills_manager import ensure_skill_pool_initialized

    if ensure_skill_pool_initialized():
        click.echo("✓ Skill pool initialized")

    # Get default workspace path for subsequent operations
    default_workspace = Path(f"{WORKING_DIR}/workspaces/default").expanduser()

    # --- config.json ---
    write_config = True
    if config_path.is_file() and not force and not use_defaults:
        prompt_text = (
            f"{config_path} exists. Do you want to overwrite it? "
            '("no" for skipping the configuration process)'
        )
        write_config = prompt_confirm(prompt_text, default=False)
    if not write_config:
        click.echo("Skipping configuration.")
    else:
        if use_defaults:
            every = HEARTBEAT_DEFAULT_EVERY
            target = "main"
            active_hours = None
        else:
            click.echo("\n=== Heartbeat Configuration ===")
            every = click.prompt(
                "Heartbeat interval (e.g. 30m, 1h)",
                default=HEARTBEAT_DEFAULT_EVERY,
                type=str,
            ).strip()

            target = prompt_choice(
                "Heartbeat target:",
                options=["main", "last"],
                default="main",
            ).lower()

            use_active = prompt_confirm(
                "Set active hours for heartbeat? (skip = run 24h)",
                default=False,
            )
            active_hours = None
            if use_active:
                start = click.prompt(
                    "Active start (HH:MM)",
                    default="08:00",
                    type=str,
                )
                end = click.prompt(
                    "Active end (HH:MM)",
                    default="22:00",
                    type=str,
                )
                active_hours = ActiveHoursConfig(
                    start=start.strip(),
                    end=end.strip(),
                )

        hb = HeartbeatConfig(
            every=every or HEARTBEAT_DEFAULT_EVERY,
            target=target or "main",
            active_hours=active_hours,
        )
        existing = (
            load_config(config_path) if config_path.is_file() else Config()
        )
        # Ensure agents.defaults exists
        if existing.agents.defaults is None:
            from ..config.config import AgentsDefaultsConfig

            existing.agents.defaults = AgentsDefaultsConfig()
        existing.agents.defaults.heartbeat = hb

        # --- show_tool_details ---
        if use_defaults:
            existing.show_tool_details = True
        else:
            existing.show_tool_details = prompt_confirm(
                "Show tool call/result details in channel messages?",
                default=True,
            )

        # --- language selection ---
        if not use_defaults:
            language = prompt_choice(
                "Select language for MD files:",
                options=["zh", "en", "ru"],
                default=existing.agents.language,
            )
            existing.agents.language = language

        # --- audio mode selection ---
        if not use_defaults:
            audio_mode = prompt_choice(
                "Select audio mode for voice messages:\n"
                "  auto   - transcribe if provider available, else file placeholder\n"
                "  native - send audio directly to model (needs ffmpeg)\n"
                "Audio mode:",
                options=["auto", "native"],
                default=existing.agents.audio_mode,
            )
            existing.agents.audio_mode = audio_mode

        # --- transcription provider type selection ---
        if not use_defaults and audio_mode != "native":
            provider_type = prompt_choice(
                "Select transcription provider:\n"
                "  disabled       - no transcription\n"
                "  whisper_api    - remote Whisper API endpoint\n"
                "  local_whisper  - locally installed openai-whisper\n"
                "                   (requires ffmpeg + openai-whisper)\n"
                "Provider:",
                options=["disabled", "whisper_api", "local_whisper"],
                default=existing.agents.transcription_provider_type,
            )
            existing.agents.transcription_provider_type = provider_type

        # --- channels (interactive when not --defaults) ---
        if not use_defaults and prompt_confirm(
            "Configure channels? "
            "(iMessage/Discord/DingTalk/Feishu/QQ/Console)",
            default=False,
        ):
            configure_channels_interactive(existing)

        save_config(existing, config_path)
        click.echo(f"\n✓ Configuration saved to {config_path}")

    # --- LLM provider and model configuration ---
    provider_manager = ProviderManager.get_instance()
    activate_llm = provider_manager.get_active_model()

    if (
        activate_llm is not None
        and activate_llm.provider_id
        and activate_llm.model
    ):
        click.echo(
            f"\n✓ LLM already configured: "
            f"{activate_llm.provider_id} / {activate_llm.model}",
        )
        if not use_defaults and prompt_confirm(
            "Reconfigure LLM provider?",
            default=False,
        ):
            click.echo("\n=== LLM Provider Configuration ===")
            configure_providers_interactive(use_defaults=False)
        else:
            click.echo("Skipped LLM configuration.")
    else:
        # No active LLM — must configure, cannot skip
        click.echo("\n=== LLM Provider Configuration (required) ===")
        configure_providers_interactive(use_defaults=use_defaults)

    # --- skills (prompt if needed) ---
    if use_defaults:
        # Using --defaults: download all pool skills into workspace, then enable
        from ..agents.skills_manager import (
            SkillPoolService,
            SkillService,
        )

        pool = SkillPoolService()
        service = SkillService(default_workspace)
        click.echo("Downloading pool skills into workspace...")
        for skill in pool.list_all_skills():
            pool.download_to_workspace(
                skill.name,
                default_workspace,
                overwrite=False,
            )
        click.echo("Enabling all skills by default...")
        synced = 0
        for skill in service.list_all_skills():
            result = service.enable_skill(skill.name)
            if result.get("success"):
                synced += 1
        click.echo(f"✓ All {synced} skills enabled.")
    elif write_config:
        # Interactive mode and config was written: prompt user
        skills_choice = prompt_choice(
            "Configure skills:",
            options=["all", "none", "custom"],
            default="all",
        )

        if skills_choice == "all":
            from ..agents.skills_manager import (
                SkillPoolService,
                SkillService,
            )

            pool = SkillPoolService()
            service = SkillService(default_workspace)
            click.echo("Downloading pool skills into workspace...")
            for skill in pool.list_all_skills():
                pool.download_to_workspace(
                    skill.name,
                    default_workspace,
                    overwrite=False,
                )
            click.echo("Enabling all skills...")
            synced = 0
            for skill in service.list_all_skills():
                result = service.enable_skill(skill.name)
                if result.get("success"):
                    synced += 1
            click.echo(f"✓ Skills synced: {synced}")
        elif skills_choice == "custom":
            configure_skills_interactive(
                agent_id="default",
                working_dir=default_workspace,
                include_pool_candidates=True,
            )
        else:  # none
            click.echo("Skipped skills configuration.")

    # --- environment variables ---
    if not use_defaults:
        if prompt_confirm(
            "Configure environment variables?",
            default=False,
        ):
            configure_env_interactive()
        else:
            click.echo("Skipped environment variable configuration.")

    # --- md files (check language change) ---
    from ..agents.utils import copy_md_files

    config = load_config(config_path) if config_path.is_file() else Config()
    current_language = (
        config.agents.language or "zh"
    )  # Default to "zh" if None
    installed_language = config.agents.installed_md_files_language

    if use_defaults:
        # --defaults: always attempt copy, skip files that already exist
        # in default workspace (handles freshly mounted empty volumes).
        click.echo(f"\nChecking MD files [language: {current_language}]...")
        copied = copy_md_files(
            current_language,
            skip_existing=True,
            workspace_dir=default_workspace,
        )
        if copied:
            config.agents.installed_md_files_language = current_language
            save_config(config, config_path)
            click.echo(
                f"✓ Copied {len(copied)} md file(s): " + ", ".join(copied),
            )
        else:
            click.echo("✓ MD files already present, skipped.")
    elif installed_language != current_language or force:
        click.echo(f"\nChecking MD files [language: {current_language}]...")
        if installed_language and installed_language != current_language:
            click.echo(
                f"Language changed: {installed_language} → {current_language}",
            )
        copied = copy_md_files(
            current_language,
            workspace_dir=default_workspace,
        )
        if copied:
            config.agents.installed_md_files_language = current_language
            save_config(config, config_path)
            click.echo(
                f"✓ Copied {len(copied)} md file(s): " + ", ".join(copied),
            )
        else:
            click.echo("⚠ No md files copied")
    else:
        click.echo(
            f"\n✓ MD files [{current_language}] are already up to date.",
        )

    # --- HEARTBEAT.md ---
    write_heartbeat = True
    if heartbeat_path.is_file() and not force:
        if use_defaults:
            click.echo("✓ HEARTBEAT.md already present, skipped.")
            write_heartbeat = False
        else:
            write_heartbeat = prompt_confirm(
                f"{heartbeat_path} exists. Overwrite?",
                default=False,
            )
    if not write_heartbeat:
        if not use_defaults:
            click.echo("Skipped HEARTBEAT.md.")
    else:
        DEFAULT_HEARTBEAT_MD = DEFAULT_HEARTBEAT_MDS[current_language]
        if use_defaults:
            content = DEFAULT_HEARTBEAT_MD
        else:
            click.echo("\n=== Heartbeat Query Configuration ===")
            if prompt_confirm(
                "Edit heartbeat query in your default editor?",
                default=True,
            ):
                content = click.edit(
                    DEFAULT_HEARTBEAT_MD,
                    extension=".md",
                    require_save=False,
                )
                if content is None:
                    content = DEFAULT_HEARTBEAT_MD
            else:
                content = DEFAULT_HEARTBEAT_MD
        heartbeat_path.write_text(
            content.strip() or DEFAULT_HEARTBEAT_MD,
            encoding="utf-8",
        )
        click.echo(f"✓ Heartbeat query saved to {heartbeat_path}")

    click.echo("\n✓ Initialization complete!")
