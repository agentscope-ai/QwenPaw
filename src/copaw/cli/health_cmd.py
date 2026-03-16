# -*- coding: utf-8 -*-
"""CLI health command: comprehensive system health check and diagnostics."""
import json
import click

from ..config.validator import ConfigValidator
from ..config.health import HealthChecker, HealthStatus


def _print_checks(health, verbose, status_icons, status_colors) -> None:
    """Print individual health check results."""
    for check in health.checks:
        icon = status_icons[check.status]
        color = status_colors[check.status]
        click.secho(f"{icon} {check.name}: ", fg=color, nl=False)
        click.echo(check.message)

        if verbose and check.details:
            for key, value in check.details.items():
                click.echo(f"  {key}: {value}")

        if check.suggestion:
            click.secho(f"  → {check.suggestion}", fg="cyan")


def _print_validation(validation) -> None:
    """Print configuration validation errors and warnings."""
    if not (validation.errors or validation.warnings):
        return

    click.echo("\n" + "=" * 60)
    click.echo("Configuration Validation")
    click.echo("=" * 60 + "\n")

    if validation.errors:
        n = len(validation.errors)
        click.secho(f"✗ Found {n} error(s):", fg="red", bold=True)
        for issue in validation.errors:
            click.secho(f"\n  {issue.path}", fg="red", bold=True)
            click.echo(f"  {issue.message}")
            if issue.suggestion:
                click.secho(f"  → {issue.suggestion}", fg="cyan")

    if validation.warnings:
        n = len(validation.warnings)
        click.secho(f"\n⚠ Found {n} warning(s):", fg="yellow", bold=True)
        for issue in validation.warnings:
            click.secho(f"\n  {issue.path}", fg="yellow", bold=True)
            click.echo(f"  {issue.message}")
            if issue.suggestion:
                click.secho(f"  → {issue.suggestion}", fg="cyan")


@click.command("health")
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output results in JSON format.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed information.",
)
def health_cmd(output_json: bool, verbose: bool) -> None:
    """Run comprehensive system health check and configuration validation.

    This command performs:
    1. System health checks (10 checks):
       - Configuration files
       - LLM providers and connection test
       - Skills availability
       - Python dependencies
       - Environment and system tools
       - Disk space
       - Channel credentials
       - MCP clients
       - Required files
       - Directory permissions

    2. Configuration validation:
       - Semantic validation of config.json
       - Channel configuration checks
       - MCP client validation
       - Agent settings validation
    """
    if not output_json:
        click.echo("\n🐾 CoPaw System Health Check\n")

    # Run health checks
    checker = HealthChecker()
    health = checker.check_all()

    # Run configuration validation
    try:
        validator = ConfigValidator()
        validation = validator.validate_all()
    except Exception as e:
        if not output_json:
            click.secho(
                f"Configuration validation failed: {e}",
                fg="red",
            )
            click.echo("Run 'copaw health' again or check config.json.")
        return

    # JSON output
    if output_json:
        result = {
            "health": {
                "status": health.status.value,
                "summary": {
                    "healthy": health.healthy_count,
                    "degraded": health.degraded_count,
                    "unhealthy": health.unhealthy_count,
                },
                "checks": [
                    {
                        "name": check.name,
                        "status": check.status.value,
                        "message": check.message,
                        "details": check.details,
                        "suggestion": check.suggestion,
                    }
                    for check in health.checks
                ],
            },
            "validation": {
                "valid": validation.valid,
                "error_count": len(validation.errors),
                "warning_count": len(validation.warnings),
                "issues": [
                    {
                        "level": issue.level.value,
                        "path": issue.path,
                        "message": issue.message,
                        "suggestion": issue.suggestion,
                        "code": issue.code,
                    }
                    for issue in validation.issues
                ],
            },
        }
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # Human-readable output
    status_icons = {
        HealthStatus.HEALTHY: "✓",
        HealthStatus.DEGRADED: "⚠",
        HealthStatus.UNHEALTHY: "✗",
    }
    status_colors = {
        HealthStatus.HEALTHY: "green",
        HealthStatus.DEGRADED: "yellow",
        HealthStatus.UNHEALTHY: "red",
    }

    _print_checks(health, verbose, status_icons, status_colors)
    _print_validation(validation)

    # Overall summary
    click.echo("\n" + "=" * 60)

    has_critical = (
        health.status == HealthStatus.UNHEALTHY or not validation.valid
    )
    has_warnings = health.status == HealthStatus.DEGRADED or bool(
        validation.warnings,
    )

    if has_critical:
        click.secho("✗ System has critical issues", fg="red", bold=True)
        click.echo(
            f"  Health: {health.unhealthy_count} critical,"
            f" {health.degraded_count} warnings",
        )
        if not validation.valid:
            click.echo(
                f"  Config: {len(validation.errors)} errors,"
                f" {len(validation.warnings)} warnings",
            )
        elif validation.warnings:
            click.echo(f"  Config: {len(validation.warnings)} warnings")
    elif has_warnings:
        click.secho(
            "⚠ System is operational with warnings",
            fg="yellow",
            bold=True,
        )
        click.echo(f"  Health: {health.degraded_count} warnings")
        if validation.warnings:
            click.echo(f"  Config: {len(validation.warnings)} warnings")
    else:
        click.secho("✓ All checks passed!", fg="green", bold=True)
