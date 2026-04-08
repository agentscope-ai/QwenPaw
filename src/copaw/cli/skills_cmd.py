# -*- coding: utf-8 -*-
"""CLI skill: list and interactively enable/disable workspace skills."""
from __future__ import annotations

from pathlib import Path

import click

from ..agents.skills_manager import (
    SkillPoolService,
    SkillService,
    read_skill_manifest,
    reconcile_pool_manifest,
    reconcile_workspace_manifest,
)
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


def _print_skill_changes(
    to_install: set[str],
    to_enable: set[str],
    to_disable: set[str],
) -> None:
    """Print preview of skill changes."""
    click.echo()
    if to_install:
        click.echo(
            click.style(
                f"  + Install: {', '.join(sorted(to_install))}",
                fg="green",
            ),
        )
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


def _apply_skill_changes(
    skill_service: SkillService,
    pool_service: SkillPoolService | None,
    working_dir: Path,
    to_install: set[str],
    to_enable: set[str],
    to_disable: set[str],
    installed_names: set[str],
) -> None:
    """Install from pool, enable, and disable skills."""
    installed_now = set(installed_names)
    if to_install and pool_service is not None:
        for name in sorted(to_install):
            result = pool_service.download_to_workspace(
                name,
                working_dir,
                overwrite=False,
            )
            if result.get("success"):
                installed_now.add(name)
                click.echo(f"  ✓ Installed: {name}")
            else:
                click.echo(
                    click.style(
                        f"  ✗ Failed to install: {name}",
                        fg="red",
                    ),
                )

    for name in sorted((to_enable | to_install) & installed_now):
        result = skill_service.enable_skill(name)
        if result.get("success"):
            click.echo(f"  ✓ Enabled: {name}")
        else:
            click.echo(
                click.style(
                    f"  ✗ Failed to enable: {name}",
                    fg="red",
                ),
            )

    for name in sorted(to_disable):
        result = skill_service.disable_skill(name)
        if result.get("success"):
            click.echo(f"  ✓ Disabled: {name}")
        else:
            click.echo(
                click.style(
                    f"  ✗ Failed to disable: {name}",
                    fg="red",
                ),
            )

    click.echo("\n✓ Skills configuration updated!")


def configure_skills_interactive(
    agent_id: str = "default",
    working_dir: Path | None = None,
    include_pool_candidates: bool = False,
) -> None:
    """Interactively select which skills to enable (multi-select)."""
    if working_dir is None:
        working_dir = _get_agent_workspace(agent_id)

    click.echo(f"Configuring skills for agent: {agent_id}\n")

    reconcile_workspace_manifest(working_dir)
    skill_service = SkillService(working_dir)
    installed_skills = skill_service.list_all_skills()
    installed_by_name = {skill.name: skill for skill in installed_skills}
    pool_candidates = {}
    pool_service = SkillPoolService() if include_pool_candidates else None
    if pool_service is not None:
        reconcile_pool_manifest()
        pool_candidates = {
            skill.name: skill
            for skill in pool_service.list_all_skills()
            if skill.name not in installed_by_name
        }

    if not installed_by_name and not pool_candidates:
        click.echo("No skills found. Nothing to configure.")
        return

    enabled = {
        name
        for name, entry in read_skill_manifest(working_dir)
        .get("skills", {})
        .items()
        if entry.get("enabled", False)
    }
    installed_names = set(installed_by_name)
    candidate_names = installed_names | set(pool_candidates)

    default_checked = enabled if enabled else candidate_names

    options: list[tuple[str, str]] = []
    for skill_name in sorted(candidate_names):
        if skill_name in installed_by_name:
            skill = installed_by_name[skill_name]
            status = "✓" if skill_name in enabled else "✗"
            label = f"{skill.name}  [{status}] ({skill.source})"
        else:
            skill = pool_candidates[skill_name]
            label = f"{skill.name}  [pool] ({skill.source})"
        options.append((label, skill.name))

    click.echo("\n=== Skills Configuration ===")
    click.echo("Use ↑/↓ to move, <space> to toggle, <enter> to confirm.\n")

    selected = prompt_checkbox(
        "Select skills to enable:",
        options=options,
        checked=default_checked,
        select_all_option=False,
    )

    if selected is None:
        click.echo("\n\nOperation cancelled.")
        return

    selected_set = set(selected)
    to_install = selected_set - installed_names
    to_enable = (selected_set & installed_names) - enabled
    to_disable = enabled - selected_set

    if not to_install and not to_enable and not to_disable:
        click.echo("\nNo changes needed.")
        return

    _print_skill_changes(to_install, to_enable, to_disable)

    save = prompt_confirm("Apply changes?", default=True)
    if not save:
        click.echo("Skipped. No changes applied.")
        return

    _apply_skill_changes(
        skill_service,
        pool_service,
        working_dir,
        to_install,
        to_enable,
        to_disable,
        installed_names,
    )


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

    reconcile_workspace_manifest(working_dir)
    skill_service = SkillService(working_dir)
    all_skills = skill_service.list_all_skills()
    enabled = {
        name
        for name, entry in read_skill_manifest(working_dir)
        .get("skills", {})
        .items()
        if entry.get("enabled", False)
    }

    if not all_skills:
        click.echo("No skills found.")
        return

    click.echo(f"\n{'─' * 50}")
    click.echo(f"  {'Skill Name':<30s} {'Source':<12s} Status")
    click.echo(f"{'─' * 50}")

    for skill in sorted(all_skills, key=lambda s: s.name):
        status = (
            click.style("✓ enabled", fg="green")
            if skill.name in enabled
            else click.style("✗ disabled", fg="red")
        )
        click.echo(f"  {skill.name:<30s} {skill.source:<12s} {status}")

    click.echo(f"{'─' * 50}")
    enabled_count = sum(1 for s in all_skills if s.name in enabled)
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
