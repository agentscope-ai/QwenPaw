# -*- coding: utf-8 -*-
"""CLI doctor command: system health check and diagnostics."""
import json
import click

from ..config.validator import ConfigValidator, ValidationLevel
from ..config.health import HealthChecker, HealthStatus


@click.group("doctor")
def doctor_group() -> None:
    """System health check and diagnostics."""


@doctor_group.command("check")
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
@click.option(
    "--test-connection",
    "-t",
    is_flag=True,
    help="Test LLM API connection (slower but more thorough).",
)
def check_cmd(output_json: bool, verbose: bool, test_connection: bool) -> None:
    """Run comprehensive health check.

    Checks:
    - Configuration files (config.json)
    - LLM providers and models
    - Skills availability
    - Python dependencies
    - Environment and system tools
    - Disk space

    Use --test-connection to actually ping the LLM API (slower).
    """
    if not output_json:
        click.echo("\n🐾 CoPaw System Health Check\n")
        if test_connection:
            click.echo("Testing LLM connection (this may take a few seconds)...\n")

    # Run health checks
    checker = HealthChecker()
    health = checker.check_all(test_connection=test_connection)

    # JSON output
    if output_json:
        result = {
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

    # Summary
    click.echo()
    if health.status == HealthStatus.HEALTHY:
        click.secho("✓ All checks passed!", fg="green", bold=True)
    elif health.status == HealthStatus.DEGRADED:
        click.secho(
            f"⚠ System is degraded ({health.degraded_count} warnings)",
            fg="yellow",
            bold=True,
        )
    else:
        click.secho(
            f"✗ System has critical issues ({health.unhealthy_count} errors)",
            fg="red",
            bold=True,
        )


@doctor_group.command("validate")
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output results in JSON format.",
)
def validate_cmd(output_json: bool) -> None:
    """Validate configuration file.

    Checks config.json for:
    - Missing required fields
    - Invalid values
    - Semantic errors
    """
    if not output_json:
        click.echo("\n🔍 Validating configuration...\n")

    # Run validation
    validator = ConfigValidator()
    result = validator.validate_all()

    # JSON output
    if output_json:
        output = {
            "valid": result.valid,
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "issues": [
                {
                    "level": issue.level.value,
                    "path": issue.path,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "code": issue.code,
                }
                for issue in result.issues
            ],
        }
        click.echo(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # Human-readable output
    if result.valid and not result.warnings:
        click.secho("✓ Configuration is valid!", fg="green", bold=True)
        return

    # Show errors
    if result.errors:
        click.secho(f"✗ Found {len(result.errors)} error(s):", fg="red", bold=True)
        for issue in result.errors:
            click.secho(f"\n  {issue.path}", fg="red", bold=True)
            click.echo(f"  {issue.message}")
            click.secho(f"  → {issue.suggestion}", fg="cyan")

    # Show warnings
    if result.warnings:
        click.secho(f"\n⚠ Found {len(result.warnings)} warning(s):", fg="yellow", bold=True)
        for issue in result.warnings:
            click.secho(f"\n  {issue.path}", fg="yellow", bold=True)
            click.echo(f"  {issue.message}")
            if issue.suggestion:
                click.secho(f"  → {issue.suggestion}", fg="cyan")

    # Summary
    click.echo()
    if result.valid:
        click.secho("Configuration is valid but has warnings.", fg="yellow")
    else:
        click.secho("Configuration has errors that must be fixed.", fg="red")
