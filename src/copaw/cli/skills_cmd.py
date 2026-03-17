# -*- coding: utf-8 -*-
"""CLI skill: list and interactively enable/disable skills."""
from __future__ import annotations

from pathlib import Path

import click

from ..agents.skills_manager import SkillService, list_available_skills
from ..constant import WORKING_DIR
from ..config import load_config
from .utils import prompt_checkbox, prompt_confirm


def _get_agent_workspace(agent_id: str) -> Path:
    """Get agent workspace directory."""
    try:
        config = load_config()
        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            workspace_dir = Path(ref.workspace_dir).expanduser()
            return workspace_dir
    except Exception:
        pass
    return WORKING_DIR


# pylint: disable=too-many-branches
def configure_skills_interactive(
    agent_id: str = "default",
    working_dir: Path | None = None,
) -> None:
    """Interactively select which skills to enable (multi-select)."""
    if working_dir is None:
        working_dir = _get_agent_workspace(agent_id)

    click.echo(f"Configuring skills for agent: {agent_id}\n")

    skill_service = SkillService(working_dir)
    all_skills = skill_service.list_all_skills()
    if not all_skills:
        click.echo("No skills found. Nothing to configure.")
        return

    available = set(list_available_skills(working_dir))
    all_names = {s.name for s in all_skills}

    # Default to all skills if nothing is currently active (first time)
    default_checked = available if available else all_names

    # Build checkbox options: (label, value)
    options: list[tuple[str, str]] = []
    for skill in sorted(all_skills, key=lambda s: s.name):
        status = "✓" if skill.name in available else "✗"
        label = f"{skill.name}  [{status}] ({skill.source})"
        options.append((label, skill.name))

    click.echo("\n=== Skills Configuration ===")
    click.echo("Use ↑/↓ to move, <space> to toggle, <enter> to confirm.\n")

    selected = prompt_checkbox(
        "Select skills to enable:",
        options=options,
        checked=default_checked,
        select_all_option=False,
    )

    # Ctrl+C → cancel
    if selected is None:
        click.echo("\n\nOperation cancelled.")
        return

    selected_set = set(selected)

    # Show preview of changes
    to_enable = selected_set - available
    to_disable = (all_names & available) - selected_set

    if not to_enable and not to_disable:
        click.echo("\nNo changes needed.")
        return

    click.echo()
    if to_enable:
        click.echo(
            click.style(
                f"  + Enable:  {', '.join(sorted(to_enable))}",
                fg="green",
            ),
        )
    if to_disable:
        click.echo(
            click.style(
                f"  - Disable: {', '.join(sorted(to_disable))}",
                fg="red",
            ),
        )

    # Confirm save or skip
    save = prompt_confirm("Apply changes?", default=True)
    if not save:
        click.echo("Skipped. No changes applied.")
        return

    # Apply changes
    for name in to_enable:
        result = skill_service.enable_skill(name)
        if result:
            click.echo(f"  ✓ Enabled: {name}")
        else:
            click.echo(
                click.style(f"  ✗ Failed to enable: {name}", fg="red"),
            )

    for name in to_disable:
        result = skill_service.disable_skill(name)
        if result:
            click.echo(f"  ✓ Disabled: {name}")
        else:
            click.echo(
                click.style(f"  ✗ Failed to disable: {name}", fg="red"),
            )

    click.echo("\n✓ Skills configuration updated!")


@click.group("skills")
def skills_group() -> None:
    """Manage skills (list / configure)."""


@skills_group.command("list")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def list_cmd(agent_id: str) -> None:
    """Show all skills and their enabled/disabled status."""
    working_dir = _get_agent_workspace(agent_id)

    click.echo(f"Skills for agent: {agent_id}\n")

    skill_service = SkillService(working_dir)
    all_skills = skill_service.list_all_skills()
    available = set(list_available_skills(working_dir))

    if not all_skills:
        click.echo("No skills found.")
        return

    click.echo(f"\n{'─' * 50}")
    click.echo(f"  {'Skill Name':<30s} {'Source':<12s} Status")
    click.echo(f"{'─' * 50}")

    for skill in sorted(all_skills, key=lambda s: s.name):
        status = (
            click.style("✓ enabled", fg="green")
            if skill.name in available
            else click.style("✗ disabled", fg="red")
        )
        click.echo(f"  {skill.name:<30s} {skill.source:<12s} {status}")

    click.echo(f"{'─' * 50}")
    enabled_count = sum(1 for s in all_skills if s.name in available)
    click.echo(
        f"  Total: {len(all_skills)} skills, "
        f"{enabled_count} enabled, "
        f"{len(all_skills) - enabled_count} disabled\n",
    )


@skills_group.command("config")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def configure_cmd(agent_id: str) -> None:
    """Interactively configure skills."""
    configure_skills_interactive(agent_id=agent_id)
