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
from ..providers import load_providers_json

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
def init_cmd(force: bool, use_defaults: bool, accept_security: bool) -> None:
    """Create working dir with config.json and HEARTBEAT.md (interactive)."""
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
                options=["zh", "en"],
                default=existing.agents.language,
            )
            existing.agents.language = language

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
    data = load_providers_json()
    has_llm = bool(data.active_llm.provider_id and data.active_llm.model)

    if has_llm:
        click.echo(
            f"\n✓ LLM already configured: "
            f"{data.active_llm.provider_id} / {data.active_llm.model}",
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
        # Using --defaults: enable all skills, skip existing
        from ..agents.skills_manager import sync_skills_to_working_dir

        click.echo("Enabling all skills by default (skip existing)...")
        synced, skipped = sync_skills_to_working_dir(
            skill_names=None,
            force=False,
        )
        if skipped:
            click.echo(
                f"✓ Skills synced: {synced}, skipped (existing): {skipped}",
            )
        else:
            click.echo(f"✓ All {synced} skills enabled.")
    elif write_config:
        # Interactive mode and config was written: prompt user
        skills_choice = prompt_choice(
            "Configure skills:",
            options=["all", "none", "custom"],
            default="all",
        )

        if skills_choice == "all":
            from ..agents.skills_manager import sync_skills_to_working_dir

            click.echo("Enabling all skills...")
            synced, skipped = sync_skills_to_working_dir(
                skill_names=None,
                force=False,
            )
            click.echo(f"✓ Skills synced: {synced}, skipped: {skipped}")
        elif skills_choice == "custom":
            configure_skills_interactive()
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
    current_language = config.agents.language
    installed_language = config.agents.installed_md_files_language

    if use_defaults:
        # --defaults: always attempt copy, skip files that already exist
        # in WORKING_DIR (handles freshly mounted empty volumes).
        click.echo(f"\nChecking MD files [language: {current_language}]...")
        copied = copy_md_files(current_language, skip_existing=True)
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
        copied = copy_md_files(current_language)
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
