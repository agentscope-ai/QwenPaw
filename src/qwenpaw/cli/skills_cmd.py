# -*- coding: utf-8 -*-
"""CLI skill: list, inspect, and interactively configure workspace skills."""
from __future__ import annotations

from pathlib import Path

import click

from ..agents.skills_manager import (
    SkillConflictError,
    SkillPoolService,
    SkillService,
    _validate_skill_content,
    get_workspace_skills_dir,
    list_workspaces,
    read_skill_pool_manifest,
    read_skill_manifest,
    reconcile_pool_manifest,
    reconcile_workspace_manifest,
)
from ..agents.skills_hub import (
    import_pool_skill_from_hub,
    install_skill_from_hub,
)
from ..agents.utils.file_handling import read_text_file_with_encoding_fallback
from ..config import load_config
from ..constant import WORKING_DIR
from ..exceptions import SkillsError
from ..security.skill_scanner import SkillScanError, scan_skill_directory
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


def _require_agent_workspace(agent_id: str) -> Path:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise click.ClickException("Agent ID cannot be empty.")
    workspaces = list_workspaces()
    for workspace in workspaces:
        if workspace.get("agent_id") == normalized_agent_id:
            return Path(str(workspace["workspace_dir"])).expanduser()

    available_agents = sorted(
        str(workspace.get("agent_id") or "")
        for workspace in workspaces
        if str(workspace.get("agent_id") or "")
    )
    if available_agents:
        raise click.ClickException(
            "Agent "
            f"'{normalized_agent_id}' not found. Available agents: "
            f"{', '.join(available_agents)}",
        )
    raise click.ClickException(
        f"Agent '{normalized_agent_id}' not found.",
    )


def _raise_conflict(exc: SkillConflictError) -> None:
    detail = exc.detail or {}
    message = str(detail.get("message") or str(exc))
    suggested_name = str(detail.get("suggested_name") or "").strip()
    if suggested_name:
        message = f"{message} Suggested name: {suggested_name}"
    raise click.ClickException(message)


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


def _validate_skill_frontmatter(skill_dir: Path) -> None:
    """Validate required skill metadata."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise click.ClickException(f"Missing SKILL.md: {skill_md}")

    content = read_text_file_with_encoding_fallback(skill_md)
    try:
        _validate_skill_content(content)
    except SkillsError as exc:
        raise click.ClickException(str(exc))
    except Exception as exc:
        raise click.ClickException(
            f"SKILL.md frontmatter is invalid: {exc}",
        ) from exc


def _resolve_skill_test_dir(skill: str, agent_id: str) -> Path:
    """Resolve a skill argument as a path first, then workspace skill name."""
    candidate = Path(skill).expanduser()
    if candidate.exists():
        return candidate.resolve()

    working_dir = _get_agent_workspace(agent_id)
    return get_workspace_skills_dir(working_dir) / skill


def _run_skill_test(skill_dir: Path) -> str:
    """Run local skill validation and security scanning."""
    if not skill_dir.is_dir():
        raise click.ClickException(f"Skill directory not found: {skill_dir}")

    skill_name = skill_dir.name
    _validate_skill_frontmatter(skill_dir)
    try:
        result = scan_skill_directory(
            skill_dir,
            skill_name=skill_name,
            block=True,
        )
    except SkillScanError as exc:
        raise click.ClickException(str(exc)) from exc

    if result is not None and not result.is_safe:
        raise click.ClickException(
            "Security scan found "
            f"{len(result.findings)} issue(s) in skill '{skill_name}'.",
        )
    return skill_name


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


@skills_group.command("info")
@click.argument("skill_name", required=True)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def info_cmd(
    skill_name: str,
    agent_id: str,
) -> None:
    """Show local details for a specific workspace skill."""
    working_dir = _get_agent_workspace(agent_id)
    reconcile_workspace_manifest(working_dir)

    skill_service = SkillService(working_dir)
    manifest = read_skill_manifest(working_dir).get("skills", {})
    skill_map = {
        skill.name: skill for skill in skill_service.list_all_skills()
    }
    skill = skill_map.get(skill_name)
    if skill is None:
        raise click.ClickException(
            f"Skill '{skill_name}' was not found for agent '{agent_id}'.",
        )

    entry = manifest.get(skill_name, {})
    channels = entry.get("channels") or ["all"]
    enabled = bool(entry.get("enabled", False))
    skill_dir = get_workspace_skills_dir(working_dir) / skill_name

    click.echo(f"Skill: {skill.name}")
    click.echo(f"Enabled: {'yes' if enabled else 'no'}")
    click.echo(f"Channels: {', '.join(channels)}")
    click.echo(f"Source: {skill.source}")
    click.echo(f"Path: {skill_dir}")
    click.echo(
        "Description: " f"{skill.description or 'No description.'}",
    )


@skills_group.command("install")
@click.argument("bundle_url", required=True)
@click.option(
    "--agent-id",
    "agent_id",
    default="",
    help="Install directly into the given agent workspace.",
)
@click.option(
    "--enable/--no-enable",
    default=True,
    help="Enable after import when installing into an agent workspace.",
)
def install_cmd(
    bundle_url: str,
    agent_id: str,
    enable: bool,
) -> None:
    """Install a skill from a URL.

    Without ``--agent-id``, the skill is imported into the local skill pool.
    With ``--agent-id``, the skill is imported directly into that workspace.
    """
    normalized_agent_id = str(agent_id or "").strip()

    try:
        if normalized_agent_id:
            workspace_dir = _require_agent_workspace(normalized_agent_id)
            result = install_skill_from_hub(
                workspace_dir=workspace_dir,
                bundle_url=bundle_url,
                enable=enable,
            )
            click.echo(
                f"✓ Installed skill '{result.name}' to agent "
                f"'{normalized_agent_id}'.",
            )
            if result.enabled:
                click.echo("✓ Skill enabled.")
            click.echo(f"Source: {result.source_url}")
            click.echo(f"Workspace: {workspace_dir}")
            return

        result = import_pool_skill_from_hub(
            bundle_url=bundle_url,
        )
        click.echo(f"✓ Installed skill '{result.name}' to the skill pool.")
        click.echo(f"Source: {result.source_url}")
    except SkillConflictError as exc:
        _raise_conflict(exc)
    except SkillScanError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@skills_group.command("uninstall")
@click.argument("skill_name", required=True)
@click.option(
    "--agent-id",
    "agent_id",
    default="",
    help="Remove the skill from the given agent workspace.",
)
def uninstall_cmd(
    skill_name: str,
    agent_id: str,
) -> None:
    """Uninstall a skill from the skill pool or one agent workspace."""
    normalized_skill_name = str(skill_name or "").strip()
    if not normalized_skill_name:
        raise click.ClickException("Skill name cannot be empty.")

    normalized_agent_id = str(agent_id or "").strip()

    try:
        if normalized_agent_id:
            workspace_dir = _require_agent_workspace(normalized_agent_id)
            manifest = read_skill_manifest(workspace_dir).get("skills", {})
            if normalized_skill_name not in manifest:
                raise click.ClickException(
                    f"Skill '{normalized_skill_name}' was not found for "
                    f"agent '{normalized_agent_id}'.",
                )

            skill_service = SkillService(workspace_dir)
            if bool(manifest[normalized_skill_name].get("enabled", False)):
                disable_result = skill_service.disable_skill(
                    normalized_skill_name,
                )
                if not disable_result.get("success"):
                    raise click.ClickException(
                        f"Failed to disable skill '{normalized_skill_name}' "
                        f"for agent '{normalized_agent_id}'.",
                    )

            deleted = skill_service.delete_skill(normalized_skill_name)
            if not deleted:
                raise click.ClickException(
                    f"Failed to uninstall skill '{normalized_skill_name}' "
                    f"from agent '{normalized_agent_id}'.",
                )

            click.echo(
                f"✓ Uninstalled skill '{normalized_skill_name}' from agent "
                f"'{normalized_agent_id}'.",
            )
            return

        manifest = read_skill_pool_manifest().get("skills", {})
        if normalized_skill_name not in manifest:
            raise click.ClickException(
                f"Skill '{normalized_skill_name}' was not found "
                "in the skill pool.",
            )

        deleted = SkillPoolService().delete_skill(normalized_skill_name)
        if not deleted:
            raise click.ClickException(
                f"Failed to uninstall skill '{normalized_skill_name}' "
                "from the skill pool.",
            )

        click.echo(
            f"✓ Uninstalled skill '{normalized_skill_name}' "
            "from the skill pool.",
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@skills_group.command("test")
@click.argument("skill", required=True)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def test_cmd(skill: str, agent_id: str) -> None:
    """Validate a workspace skill or local skill directory."""
    skill_dir = _resolve_skill_test_dir(skill, agent_id)
    skill_name = _run_skill_test(skill_dir)
    click.echo(f"Skill test passed: {skill_name}")
    click.echo(f"Path: {skill_dir}")
