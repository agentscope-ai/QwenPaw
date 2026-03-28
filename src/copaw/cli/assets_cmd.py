# -*- coding: utf-8 -*-
"""CLI commands for asset export/import: ``copaw assets export|import``."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click

from ..backup.models import AssetType, ConflictStrategy
from ..config import load_config
from ..constant import WORKING_DIR


_VALID_TYPES = {t.value for t in AssetType}


def _get_workspace_dir(agent_id: str = "default") -> Path:
    """Resolve workspace directory for the given agent."""
    try:
        config = load_config()
        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            return Path(ref.workspace_dir).expanduser()
    except Exception:
        pass
    return WORKING_DIR


def _get_all_agent_ids() -> list[str]:
    """Return all configured agent IDs."""
    try:
        config = load_config()
        return list(config.agents.profiles.keys())
    except Exception:
        return ["default"]


def _parse_types(types_str: Optional[str]) -> Optional[list[AssetType]]:
    """Parse comma-separated asset type string into a list of AssetType."""
    if types_str is None:
        return None
    parts = [t.strip().lower() for t in types_str.split(",") if t.strip()]
    result: list[AssetType] = []
    for p in parts:
        if p not in _VALID_TYPES:
            raise click.BadParameter(
                f"Invalid asset type: {p!r}. "
                f"Valid types: {', '.join(sorted(_VALID_TYPES))}",
            )
        result.append(AssetType(p))
    return result or None


@click.group("assets")
def assets_group() -> None:
    """Manage user asset export and import."""


@assets_group.command("export")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output ZIP file path. Defaults to auto-generated name.",
)
@click.option(
    "--types",
    "-t",
    default=None,
    help=(
        "Comma-separated asset types to export"
        " (preferences,memories,skills,tools,"
        "global_config). Defaults to all."
    ),
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default').",
)
@click.option(
    "--all",
    "export_all",
    is_flag=True,
    default=False,
    help="Export all agents.",
)
def export_cmd(
    output: Optional[str],
    types: Optional[str],
    agent_id: str,
    export_all: bool,
) -> None:
    """Export workspace assets to a ZIP package."""
    from ..backup.exporter import AssetExporter, ExportOptions

    agent_ids = _get_all_agent_ids() if export_all else [agent_id]
    asset_types = _parse_types(types)

    total_exported = 0
    for aid in agent_ids:
        workspace_dir = _get_workspace_dir(aid)

        include_all = asset_types is None
        types_list = asset_types or []
        options = ExportOptions(
            workspace_dir=workspace_dir,
            include_preferences=include_all
            or AssetType.PREFERENCES in types_list,
            include_memories=include_all or AssetType.MEMORIES in types_list,
            include_skills=include_all or AssetType.SKILLS in types_list,
            include_tools=include_all or AssetType.TOOLS in types_list,
            include_global_config=include_all
            or AssetType.GLOBAL_CONFIG in types_list,
            output_path=Path(output).expanduser()
            if output and not export_all
            else None,
        )

        click.echo(f"Exporting assets for agent '{aid}': {workspace_dir}")
        if types_list:
            click.echo(
                f"  Types: {', '.join(t.value for t in types_list)}",
            )

        try:
            exporter = AssetExporter()
            result = asyncio.run(exporter.export_assets(options))
            click.echo(
                click.style(
                    f"  ✓ {result.asset_count} assets, "
                    f"{result.total_size_bytes:,} bytes"
                    f" → {result.zip_path.name}",
                    fg="green",
                ),
            )
            total_exported += 1
        except Exception as exc:
            click.echo(
                click.style(f"  ✗ Export failed: {exc}", fg="red"),
                err=True,
            )
            if not export_all:
                raise SystemExit(1) from exc

    if export_all:
        click.echo(
            click.style(
                f"\n✓ Exported {total_exported}/{len(agent_ids)} agent(s)",
                fg="green",
            ),
        )


@assets_group.command("import")
@click.argument("zip_path", type=click.Path(exists=True))
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(
        ["skip", "overwrite", "rename", "ask"],
        case_sensitive=False,
    ),
    default="ask",
    help="Conflict resolution strategy (default: ask).",
)
@click.option(
    "--types",
    "-t",
    default=None,
    help=(
        "Comma-separated asset types to import"
        " (preferences,memories,skills,tools,"
        "global_config). Defaults to all."
    ),
)
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default').",
)
def import_cmd(
    zip_path: str,
    strategy: str,
    types: Optional[str],
    agent_id: str,
) -> None:
    """Import assets from a ZIP package into the workspace."""
    from ..backup.importer import AssetImporter

    workspace_dir = _get_workspace_dir(agent_id)
    asset_types = _parse_types(types)
    conflict_strategy = ConflictStrategy(strategy.lower())

    click.echo(f"Importing assets to workspace: {workspace_dir}")
    click.echo(f"  Source: {zip_path}")
    click.echo(f"  Strategy: {conflict_strategy.value}")
    if asset_types:
        types_list = asset_types or []
        click.echo(
            f"  Types: {', '.join(t.value for t in types_list)}",
        )

    try:
        importer = AssetImporter(workspace_dir=workspace_dir)
        result = asyncio.run(
            importer.import_assets(
                zip_path=Path(zip_path).expanduser(),
                strategy=conflict_strategy,
                asset_types=asset_types,
            ),
        )
        click.echo(
            click.style(
                f"\n✓ Import complete: {len(result.imported)} imported, "
                f"{len(result.skipped)} skipped, "
                f"{len(result.conflicts)} conflicts",
                fg="green",
            ),
        )
        if result.errors:
            for err in result.errors:
                click.echo(click.style(f"  ⚠ {err}", fg="yellow"))
    except Exception as exc:
        click.echo(
            click.style(f"\n✗ Import failed: {exc}", fg="red"),
            err=True,
        )
        raise SystemExit(1) from exc


@assets_group.command("verify")
@click.argument("zip_path", type=click.Path(exists=True))
def verify_cmd(zip_path: str) -> None:
    """Verify a ZIP asset package.

    Check structure, manifest, and version compatibility.
    """
    from ..backup.version_checker import (
        validate_package,
        CURRENT_SCHEMA_VERSION,
    )

    result = validate_package(Path(zip_path).expanduser())

    click.echo(f"\nVerifying: {zip_path}")
    click.echo(f"Current system schema: {CURRENT_SCHEMA_VERSION}")
    click.echo(f"{'─' * 60}")

    # Compatibility
    compat = result.get("compatibility")
    if compat:
        level = compat.level
        color = {
            "full": "green",
            "migratable": "yellow",
            "incompatible": "red",
        }.get(level.value, "white")
        if compat.source_version:
            sv = compat.source_version
            click.echo(
                f"  Schema version:  " f"{sv.prefix}.v{sv.major}.{sv.minor}",
            )
        else:
            click.echo("  Schema version:  unknown")
        click.echo(
            click.style(f"  Compatibility:   {level.value.upper()}", fg=color),
        )
        if compat.migration_needed:
            click.echo(
                f"  Migration path:  {' → '.join(compat.migration_path)}",
            )
        if compat.message:
            click.echo(f"  Message:         {compat.message}")

    # Manifest issues
    if result["manifest_issues"]:
        click.echo(f"\n  Manifest issues ({len(result['manifest_issues'])}):")
        for issue in result["manifest_issues"]:
            click.echo(click.style(f"    ✗ {issue}", fg="red"))

    # ZIP issues
    if result["zip_issues"]:
        click.echo(f"\n  ZIP issues ({len(result['zip_issues'])}):")
        for issue in result["zip_issues"]:
            click.echo(click.style(f"    ✗ {issue}", fg="red"))

    # Summary
    click.echo(f"{'─' * 60}")
    if result["valid"]:
        click.echo(
            click.style("  ✓ Package is valid and compatible", fg="green"),
        )
    else:
        click.echo(click.style("  ✗ Package has issues", fg="red"))
        raise SystemExit(1)
