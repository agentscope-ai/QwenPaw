# -*- coding: utf-8 -*-
"""CLI skill: list, inspect, and interactively configure workspace skills."""
from __future__ import annotations

import asyncio
from pathlib import Path

import click

from ..agents.skill_system import (
    SkillConflictError,
    SkillPoolService,
    SkillService,
    get_skill_pool_dir,
    get_workspace_skills_dir,
    read_skill_pool_manifest,
    read_skill_manifest,
    reconcile_pool_manifest,
    reconcile_workspace_manifest,
    resolve_pool_skill_dir,
)
from ..agents.skill_system.store import validate_skill_content
from ..agents.skill_system.hub import (
    aclose_hub_client,
    import_pool_skill_from_hub,
    install_skill_from_hub,
)
from ..agents.utils.file_handling import read_text_file_with_encoding_fallback
from ..config import load_config
from ..exceptions import SkillsError
from ..security.skill_scanner import SkillScanError, scan_skill_directory
from .utils import prompt_checkbox, prompt_confirm


def _get_agent_workspace(agent_id: str) -> Path:
    """Resolve an agent workspace without falling back to another scope."""
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise click.ClickException("Agent ID cannot be empty.")

    try:
        config = load_config()
    except Exception as exc:
        raise click.ClickException(
            f"Failed to load agent configuration: {exc}",
        ) from exc

    profiles = config.agents.profiles
    ref = profiles.get(normalized_agent_id)
    if ref is not None:
        return Path(ref.workspace_dir).expanduser()

    available_agents = sorted(str(name) for name in profiles)
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
        validate_skill_content(content)
    except SkillsError as exc:
        raise click.ClickException(str(exc))
    except Exception as exc:
        raise click.ClickException(
            f"SKILL.md frontmatter is invalid: {exc}",
        ) from exc


def _resolve_scope(
    agent_id: str | None,
    pool: bool,
    *,
    default_pool: bool = False,
) -> str | None:
    """Return an agent ID, or ``None`` for the shared skill pool."""
    normalized_agent_id = str(agent_id or "").strip()
    if pool and normalized_agent_id:
        raise click.ClickException(
            "--pool and --agent-id are mutually exclusive.",
        )
    if pool or (default_pool and not normalized_agent_id):
        return None
    return normalized_agent_id or "default"


def _resolve_skill_test_dir(
    skill: str,
    agent_id: str | None,
    *,
    pool: bool = False,
) -> Path:
    """Resolve a skill argument as a path first, then workspace skill name."""
    candidate = Path(skill).expanduser()
    if candidate.exists():
        return candidate.resolve()

    if pool:
        reconcile_pool_manifest()
        return resolve_pool_skill_dir(skill) or get_skill_pool_dir() / skill

    working_dir = _get_agent_workspace(agent_id or "default")
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


def _install_selected_skills(
    pool_service: SkillPoolService | None,
    working_dir: Path,
    to_install: set[str],
    installed_names: set[str],
) -> tuple[set[str], list[str]]:
    """Install selected pool entries and return installed names + failures."""
    installed_now = set(installed_names)
    failures: list[str] = []
    if pool_service is None:
        for name in sorted(to_install):
            failure = f"install {name} (pool unavailable)"
            failures.append(failure)
            click.echo(click.style(f"  ✗ Failed to {failure}", fg="red"))
        return installed_now, failures

    for name in sorted(to_install):
        try:
            result = pool_service.download_to_workspace(
                name,
                working_dir,
                overwrite=False,
            )
        except Exception as exc:  # noqa: BLE001 - report every item
            result = {"success": False, "reason": str(exc)}
        if result.get("success"):
            installed_now.add(name)
            click.echo(f"  ✓ Installed: {name}")
            continue
        reason = str(result.get("reason") or "operation failed")
        failures.append(f"install {name} ({reason})")
        click.echo(
            click.style(
                f"  ✗ Failed to install: {name} ({reason})",
                fg="red",
            ),
        )
    return installed_now, failures


def _apply_skill_state_changes(
    skill_service: SkillService,
    skill_names: set[str],
    *,
    enabled: bool,
) -> list[str]:
    """Apply one state to exact skill names and return failure summaries."""
    failures: list[str] = []
    action = "enable" if enabled else "disable"
    past_tense = "Enabled" if enabled else "Disabled"

    for name in sorted(skill_names):
        try:
            result = (
                skill_service.enable_skill(name)
                if enabled
                else skill_service.disable_skill(name)
            )
        except Exception as exc:  # noqa: BLE001 - report every item
            result = {"success": False, "reason": str(exc)}
        if result.get("success"):
            click.echo(f"  ✓ {past_tense}: {name}")
            continue
        reason = str(result.get("reason") or "operation failed")
        failures.append(f"{action} {name} ({reason})")
        click.echo(
            click.style(
                f"  ✗ Failed to {action}: {name} ({reason})",
                fg="red",
            ),
        )
    return failures


def _apply_skill_changes(
    skill_service: SkillService,
    pool_service: SkillPoolService | None,
    working_dir: Path,
    *,
    to_install: set[str],
    to_enable: set[str],
    to_disable: set[str],
    installed_names: set[str],
) -> None:
    """Install from pool, enable, and disable skills."""
    installed_now, failures = _install_selected_skills(
        pool_service,
        working_dir,
        to_install,
        installed_names,
    )
    failures.extend(
        _apply_skill_state_changes(
            skill_service,
            (to_enable | to_install) & installed_now,
            enabled=True,
        ),
    )
    failures.extend(
        _apply_skill_state_changes(
            skill_service,
            to_disable,
            enabled=False,
        ),
    )

    if failures:
        raise click.ClickException(
            f"{len(failures)} skill change(s) failed: " + "; ".join(failures),
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
    default_checked = enabled

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
    click.echo(
        "Type to filter, use ↑/↓ to move, <space> to toggle, "
        "<enter> to confirm.\n",
    )

    selected = prompt_checkbox(
        "Select skills to enable:",
        options=options,
        checked=default_checked,
        select_all_option=False,
        searchable=True,
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
        to_install=to_install,
        to_enable=to_enable,
        to_disable=to_disable,
        installed_names=installed_names,
    )


@click.group("skills")
def skills_group() -> None:
    """Manage workspace and skill-pool skills."""


@skills_group.command("list")
@click.option(
    "--agent-id",
    default=None,
    help="Target agent ID (defaults to 'default').",
)
@click.option(
    "--pool",
    is_flag=True,
    help="List the shared skill pool instead of an agent workspace.",
)
@click.option(
    "--status",
    type=click.Choice(["all", "enabled", "disabled"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Filter by enabled status.",
)
def list_cmd(agent_id: str | None, pool: bool, status: str) -> None:
    """Show skills in an agent workspace or the shared pool."""
    scope = _resolve_scope(agent_id, pool)
    if scope is None:
        if status.lower() != "all":
            raise click.ClickException(
                "--status is not supported with --pool; pool skills have no "
                "enabled state.",
            )
        reconcile_pool_manifest()
        all_skills = SkillPoolService().list_all_skills()
        click.echo("Skills in shared pool:\n")
        if not all_skills:
            click.echo("No skills found.")
            return
        click.echo(f"{'─' * 50}")
        click.echo(f"  {'Skill Name':<30s} Source")
        click.echo(f"{'─' * 50}")
        for skill in sorted(all_skills, key=lambda item: item.name):
            click.echo(f"  {skill.name:<30s} {skill.source}")
        click.echo(f"{'─' * 50}")
        click.echo(f"  Total: {len(all_skills)} skills\n")
        return

    working_dir = _get_agent_workspace(scope)

    click.echo(f"Skills for agent: {scope}\n")

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

    normalized_status = status.lower()
    visible_skills = []
    for skill in all_skills:
        is_enabled = skill.name in enabled
        if normalized_status == "enabled" and not is_enabled:
            continue
        if normalized_status == "disabled" and is_enabled:
            continue
        visible_skills.append(skill)

    if not visible_skills:
        click.echo("No skills match the current filters.")
        return

    click.echo(f"\n{'─' * 50}")
    click.echo(f"  {'Skill Name':<30s} {'Source':<12s} Status")
    click.echo(f"{'─' * 50}")

    for skill in sorted(visible_skills, key=lambda s: s.name):
        status = (
            click.style("✓ enabled", fg="green")
            if skill.name in enabled
            else click.style("✗ disabled", fg="red")
        )
        click.echo(f"  {skill.name:<30s} {skill.source:<12s} {status}")

    click.echo(f"{'─' * 50}")
    enabled_count = sum(1 for s in visible_skills if s.name in enabled)
    click.echo(
        f"  Showing: {len(visible_skills)} of {len(all_skills)} skills, "
        f"{enabled_count} enabled, "
        f"{len(visible_skills) - enabled_count} disabled\n",
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


def _set_skills_enabled(
    skill_names: tuple[str, ...],
    agent_id: str,
    *,
    enabled: bool,
) -> None:
    """Set exact workspace skill names and report every failure."""
    working_dir = _get_agent_workspace(agent_id)
    manifest = reconcile_workspace_manifest(working_dir).get("skills", {})
    service = SkillService(working_dir)
    action = "enable" if enabled else "disable"
    past_tense = "Enabled" if enabled else "Disabled"
    failures: list[str] = []
    seen: set[str] = set()

    for raw_name in skill_names:
        name = str(raw_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if name not in manifest:
            failures.append(f"{name} (not found)")
            click.echo(
                click.style(
                    f"  ✗ Failed to {action}: {name} (not found)",
                    fg="red",
                ),
            )
            continue

        try:
            result = (
                service.enable_skill(name)
                if enabled
                else service.disable_skill(name)
            )
        except Exception as exc:  # noqa: BLE001 - continue batch reporting
            result = {"success": False, "reason": str(exc)}

        if result.get("success"):
            click.echo(f"  ✓ {past_tense}: {name}")
            continue

        reason = str(result.get("reason") or "operation failed")
        failures.append(f"{name} ({reason})")
        click.echo(
            click.style(
                f"  ✗ Failed to {action}: {name} ({reason})",
                fg="red",
            ),
        )

    if failures:
        raise click.ClickException(
            f"Failed to {action} {len(failures)} skill(s): "
            + "; ".join(failures),
        )


@skills_group.command("enable")
@click.argument("skill_names", nargs=-1, required=True)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def enable_cmd(skill_names: tuple[str, ...], agent_id: str) -> None:
    """Enable one or more exact workspace skill names."""
    _set_skills_enabled(skill_names, agent_id, enabled=True)


@skills_group.command("disable")
@click.argument("skill_names", nargs=-1, required=True)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def disable_cmd(skill_names: tuple[str, ...], agent_id: str) -> None:
    """Disable one or more exact workspace skill names."""
    _set_skills_enabled(skill_names, agent_id, enabled=False)


@skills_group.command("info")
@click.argument("skill_name", required=True)
@click.option(
    "--agent-id",
    default=None,
    help="Target agent ID (defaults to 'default').",
)
@click.option(
    "--pool",
    is_flag=True,
    help="Inspect the skill in the shared pool.",
)
def info_cmd(
    skill_name: str,
    agent_id: str | None,
    pool: bool,
) -> None:
    """Show local details for a workspace or pool skill."""
    scope = _resolve_scope(agent_id, pool)
    if scope is None:
        reconcile_pool_manifest()
        skill_map = {
            skill.name: skill for skill in SkillPoolService().list_all_skills()
        }
        skill = skill_map.get(skill_name)
        if skill is None:
            raise click.ClickException(
                f"Skill '{skill_name}' was not found in the skill pool.",
            )
        entry = (
            read_skill_pool_manifest()
            .get("skills", {})
            .get(
                skill_name,
                {},
            )
        )
        skill_dir = resolve_pool_skill_dir(skill_name) or (
            get_skill_pool_dir() / skill_name
        )
        click.echo(f"Skill: {skill.name}")
        click.echo("Scope: pool")
        click.echo(f"Source: {skill.source}")
        click.echo(f"Path: {skill_dir}")
        click.echo(f"Description: {skill.description or 'No description.'}")
        tags = entry.get("tags") or []
        if tags:
            click.echo(f"Tags: {', '.join(str(tag) for tag in tags)}")
        return

    working_dir = _get_agent_workspace(scope)
    reconcile_workspace_manifest(working_dir)

    skill_service = SkillService(working_dir)
    manifest = read_skill_manifest(working_dir).get("skills", {})
    skill_map = {
        skill.name: skill for skill in skill_service.list_all_skills()
    }
    skill = skill_map.get(skill_name)
    if skill is None:
        raise click.ClickException(
            f"Skill '{skill_name}' was not found for agent '{scope}'.",
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
    "--pool",
    is_flag=True,
    help="Install into the shared skill pool (the default for compatibility).",
)
@click.option(
    "--enable/--no-enable",
    default=True,
    help="Enable after import when installing into an agent workspace.",
)
def install_cmd(
    bundle_url: str,
    agent_id: str,
    pool: bool,
    enable: bool,
) -> None:
    """Install a skill from a URL.

    Without ``--agent-id``, the skill is imported into the local skill pool.
    With ``--agent-id``, the skill is imported directly into that workspace.
    """
    normalized_agent_id = _resolve_scope(
        agent_id,
        pool,
        default_pool=True,
    )
    if normalized_agent_id is None and not enable:
        raise click.ClickException(
            "--no-enable is only supported with --agent-id; "
            "pool skills have no enabled state.",
        )
    workspace_dir = (
        _get_agent_workspace(normalized_agent_id)
        if normalized_agent_id
        else None
    )

    async def _run_install() -> object:
        try:
            if workspace_dir is not None:
                return await install_skill_from_hub(
                    workspace_dir=workspace_dir,
                    bundle_url=bundle_url,
                    enable=enable,
                )
            return await import_pool_skill_from_hub(bundle_url=bundle_url)
        finally:
            await aclose_hub_client()

    try:
        result = asyncio.run(_run_install())
        if workspace_dir is not None:
            click.echo(
                f"✓ Installed skill '{result.name}' to agent "
                f"'{normalized_agent_id}'.",
            )
            if result.enabled:
                click.echo("✓ Skill enabled.")
            click.echo(f"Source: {result.source_url}")
            click.echo(f"Workspace: {workspace_dir}")
            return

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
@click.option(
    "--pool",
    is_flag=True,
    help="Remove from the shared skill pool (the default for compatibility).",
)
def uninstall_cmd(
    skill_name: str,
    agent_id: str,
    pool: bool,
) -> None:
    """Uninstall a skill from the skill pool or one agent workspace."""
    normalized_skill_name = str(skill_name or "").strip()
    if not normalized_skill_name:
        raise click.ClickException("Skill name cannot be empty.")

    normalized_agent_id = _resolve_scope(
        agent_id,
        pool,
        default_pool=True,
    )

    try:
        if normalized_agent_id:
            workspace_dir = _get_agent_workspace(normalized_agent_id)
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
    default=None,
    help="Target agent ID (defaults to 'default').",
)
@click.option(
    "--pool",
    is_flag=True,
    help="Resolve the skill name from the shared pool.",
)
def test_cmd(skill: str, agent_id: str | None, pool: bool) -> None:
    """Validate a workspace skill, pool skill, or local skill directory."""
    scope = _resolve_scope(agent_id, pool)
    skill_dir = _resolve_skill_test_dir(
        skill,
        scope,
        pool=scope is None,
    )
    skill_name = _run_skill_test(skill_dir)
    click.echo(f"Skill test passed: {skill_name}")
    click.echo(f"Path: {skill_dir}")
