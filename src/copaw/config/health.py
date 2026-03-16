# -*- coding: utf-8 -*-
"""System health checks for CoPaw."""
from __future__ import annotations

import importlib
import logging
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..constant import WORKING_DIR, ACTIVE_SKILLS_DIR

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"  # Partial functionality
    UNHEALTHY = "unhealthy"  # Critical issues


@dataclass
class HealthCheckResult:
    """Single health check result."""

    name: str
    status: HealthStatus
    message: str
    details: dict = field(default_factory=dict)
    suggestion: str = ""


@dataclass
class SystemHealth:
    """Overall system health."""

    status: HealthStatus
    checks: list[HealthCheckResult]

    @property
    def healthy_count(self) -> int:
        return sum(1 for c in self.checks if c.status == HealthStatus.HEALTHY)

    @property
    def degraded_count(self) -> int:
        return sum(1 for c in self.checks if c.status == HealthStatus.DEGRADED)

    @property
    def unhealthy_count(self) -> int:
        return sum(
            1 for c in self.checks if c.status == HealthStatus.UNHEALTHY
        )


class HealthChecker:
    """Performs system health checks."""

    def __init__(self):
        self.results: list[HealthCheckResult] = []

    def check_all(self) -> SystemHealth:
        """Run all health checks (including LLM connection test).

        Each check is wrapped in exception handling to ensure one failing check
        doesn't prevent other checks from running.
        """
        self.results = []

        self._safe_check("config_files", self.check_config_files)
        self._safe_check(
            "providers",
            lambda: self.check_providers(test_connection=True),
        )
        self._safe_check("skills", self.check_skills)
        self._safe_check("dependencies", self.check_dependencies)
        self._safe_check("environment", self.check_environment)
        self._safe_check("disk_space", self.check_disk_space)
        self._safe_check("channels", self.check_channels)
        self._safe_check("mcp_clients", self.check_mcp_clients)
        self._safe_check("required_files", self.check_required_files)
        self._safe_check("permissions", self.check_permissions)

        if any(r.status == HealthStatus.UNHEALTHY for r in self.results):
            overall = HealthStatus.UNHEALTHY
        elif any(r.status == HealthStatus.DEGRADED for r in self.results):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return SystemHealth(status=overall, checks=self.results)

    def _safe_check(self, check_name: str, check_func) -> None:
        """Run a health check with exception protection.

        If the check raises an unexpected exception, record it as UNHEALTHY
        instead of aborting the entire health check process.
        """
        try:
            check_func()
        except Exception as e:
            logger.exception(f"Unexpected error in {check_name} check")
            self._add_result(
                check_name,
                HealthStatus.UNHEALTHY,
                f"Check failed with unexpected error: {type(e).__name__}: {e}",
                suggestion=(
                    "This is an unexpected error. "
                    "Please report this issue with the error details."
                ),
            )

    def _add_result(
        self,
        name: str,
        status: HealthStatus,
        message: str,
        details: Optional[dict] = None,
        suggestion: str = "",
    ) -> None:
        self.results.append(
            HealthCheckResult(
                name=name,
                status=status,
                message=message,
                details=details or {},
                suggestion=suggestion,
            ),
        )

    def check_config_files(self) -> None:
        """Check if essential config files exist."""
        from .utils import get_config_path

        config_path = get_config_path()

        if not config_path.exists():
            self._add_result(
                "config_files",
                HealthStatus.UNHEALTHY,
                f"config.json not found at {config_path}",
                suggestion="Run 'copaw init' to create configuration.",
            )
            return

        try:
            from .utils import load_config

            load_config(config_path)

            self._add_result(
                "config_files",
                HealthStatus.HEALTHY,
                "Configuration files are present",
                details={"config_path": str(config_path)},
            )
        except Exception as e:
            self._add_result(
                "config_files",
                HealthStatus.UNHEALTHY,
                f"Failed to load config.json: {e}",
                suggestion=(
                    "Check config.json syntax or run 'copaw init --force'."
                ),
            )

    def check_providers(self, test_connection: bool = False) -> None:
        """Check if LLM providers are configured.

        Args:
            test_connection: If True, actually test the API connection.
        """
        try:
            from ..providers import ProviderManager

            manager = ProviderManager.get_instance()
            active = manager.get_active_model()

            if not active or not active.provider_id or not active.model:
                self._add_result(
                    "providers",
                    HealthStatus.UNHEALTHY,
                    "No active LLM configured",
                    suggestion="Run 'copaw models' to configure a model.",
                )
                return

            provider = manager.get_provider(active.provider_id)

            if not provider:
                self._add_result(
                    "providers",
                    HealthStatus.UNHEALTHY,
                    f"Active provider '{active.provider_id}' not found",
                    suggestion=(
                        "Run 'copaw models' to select a valid provider."
                    ),
                )
                return

            if provider.require_api_key and not provider.api_key:
                self._add_result(
                    "providers",
                    HealthStatus.UNHEALTHY,
                    f"Provider '{provider.name}' is not configured",
                    suggestion=(
                        f"Configure {provider.name} API key"
                        f" via 'copaw models'."
                    ),
                )
                return

            if test_connection:
                connection_ok = self._test_llm_connection()
                if not connection_ok:
                    self._add_result(
                        "providers",
                        HealthStatus.DEGRADED,
                        (
                            f"Provider configured but connection"
                            f" test failed: {provider.name}"
                            f" / {active.model}"
                        ),
                        details={
                            "provider": active.provider_id,
                            "model": active.model,
                        },
                        suggestion=(
                            "Check API key, network connection,"
                            " and API endpoint availability."
                        ),
                    )
                    return

            self._add_result(
                "providers",
                HealthStatus.HEALTHY,
                f"Active LLM: {provider.name} / {active.model}"
                + (" (connection verified)" if test_connection else ""),
                details={
                    "provider": active.provider_id,
                    "model": active.model,
                    "connection_tested": test_connection,
                },
            )

        except Exception as e:
            self._add_result(
                "providers",
                HealthStatus.DEGRADED,
                f"Failed to check providers: {e}",
            )

    def check_skills(self) -> None:
        """Check if skills directory exists and has skills."""
        skills_dir = ACTIVE_SKILLS_DIR

        if not skills_dir.exists():
            self._add_result(
                "skills",
                HealthStatus.DEGRADED,
                f"Active skills directory not found: {skills_dir}",
                suggestion=(
                    "Run 'copaw init' or 'copaw skills config'"
                    " to enable skills."
                ),
            )
            return

        skill_count = sum(
            1
            for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        )

        if skill_count == 0:
            self._add_result(
                "skills",
                HealthStatus.DEGRADED,
                "No skills are enabled",
                suggestion="Run 'copaw skills config' to enable skills.",
            )
        else:
            self._add_result(
                "skills",
                HealthStatus.HEALTHY,
                f"{skill_count} skill(s) enabled",
                details={"count": skill_count, "path": str(skills_dir)},
            )

    def check_dependencies(self) -> None:
        """Check if required Python packages are installed."""
        required = [
            ("agentscope", "AgentScope framework"),
            ("click", "CLI framework"),
            ("pydantic", "Configuration validation"),
        ]

        missing_required = []

        for package, desc in required:
            try:
                importlib.import_module(package)
            except ImportError:
                missing_required.append(f"{package} ({desc})")

        if missing_required:
            self._add_result(
                "dependencies",
                HealthStatus.UNHEALTHY,
                f"Missing required packages: {', '.join(missing_required)}",
                suggestion="Run 'pip install copaw' to install dependencies.",
            )
        else:
            self._add_result(
                "dependencies",
                HealthStatus.HEALTHY,
                "All required dependencies are installed",
            )

    def check_environment(self) -> None:
        """Check environment variables and system tools."""
        issues = []

        py_version = sys.version_info
        if py_version < (3, 10):
            issues.append(
                f"Python {py_version.major}.{py_version.minor} "
                f"(requires >= 3.10)",
            )

        if issues:
            self._add_result(
                "environment",
                HealthStatus.DEGRADED,
                f"Environment issues: {'; '.join(issues)}",
                suggestion="Upgrade Python to 3.10 or higher.",
            )
        else:
            self._add_result(
                "environment",
                HealthStatus.HEALTHY,
                "Environment is properly configured",
                details={
                    "python_version": (
                        f"{py_version.major}"
                        f".{py_version.minor}"
                        f".{py_version.micro}"
                    ),
                    "platform": sys.platform,
                },
            )

    def check_disk_space(self) -> None:
        """Check available disk space in working directory."""
        try:
            stat = shutil.disk_usage(WORKING_DIR)
            free_gb = stat.free / (1024**3)

            if free_gb < 1.0:
                status = HealthStatus.UNHEALTHY
                message = f"Very low disk space: {free_gb:.1f} GB free"
                suggestion = "Free up disk space to avoid issues."
            elif free_gb < 5.0:
                status = HealthStatus.DEGRADED
                message = f"Low disk space: {free_gb:.1f} GB free"
                suggestion = "Consider freeing up disk space."
            else:
                status = HealthStatus.HEALTHY
                message = f"Sufficient disk space: {free_gb:.1f} GB free"
                suggestion = ""

            self._add_result(
                "disk_space",
                status,
                message,
                details={"free_gb": round(free_gb, 2)},
                suggestion=suggestion,
            )

        except Exception as e:
            self._add_result(
                "disk_space",
                HealthStatus.DEGRADED,
                f"Failed to check disk space: {e}",
            )

    async def _async_test_llm_connection(self) -> bool:
        """Async helper to test LLM connection."""
        try:
            from ..agents.model_factory import create_model_and_formatter

            model_instance, _ = create_model_and_formatter()
            await model_instance(
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )
            return True

        except ImportError as e:
            logger.error(f"Failed to import model factory: {e}")
            return False
        except ValueError as e:
            logger.error(f"Invalid model configuration: {e}")
            return False
        except ConnectionError as e:
            logger.warning(f"Network connection failed: {e}")
            return False
        except Exception as e:
            logger.warning(f"LLM connection test failed: {e}")
            return False

    def _test_llm_connection(self) -> bool:
        """Test LLM API connection with a simple request."""
        import asyncio
        import concurrent.futures

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    self._async_test_llm_connection(),
                )
                return future.result()
        except RuntimeError:
            return asyncio.run(self._async_test_llm_connection())

    def check_channels(self) -> None:
        """Check enabled channels configuration."""
        try:
            from .config import ChannelConfig
            from .utils import load_config
            from .validator import ConfigValidator

            config = load_config()
            enabled_channels = [
                name
                for name in ChannelConfig.model_fields
                if getattr(
                    getattr(config.channels, name, None),
                    "enabled",
                    False,
                )
            ]

            result = ConfigValidator(config).validate_all()
            channel_issues = [
                i for i in result.issues if i.path.startswith("channels.")
            ]

            if not enabled_channels:
                self._add_result(
                    "channels",
                    HealthStatus.DEGRADED,
                    "No channels are enabled",
                    suggestion=(
                        "Enable at least one channel via"
                        " 'copaw channels config'."
                    ),
                )
            elif channel_issues:
                issue_list = [
                    f"{i.path.split('.')[-2]}: {i.message}"
                    for i in channel_issues
                ]
                n_ch = len(enabled_channels)
                n_is = len(channel_issues)
                self._add_result(
                    "channels",
                    HealthStatus.UNHEALTHY,
                    f"{n_ch} channel(s) enabled, but {n_is} have issues",
                    details={
                        "enabled": enabled_channels,
                        "issues": issue_list,
                    },
                    suggestion=(
                        "Fix channel credentials via 'copaw channels config'."
                    ),
                )
            else:
                n_ch = len(enabled_channels)
                self._add_result(
                    "channels",
                    HealthStatus.HEALTHY,
                    f"{n_ch} channel(s) properly configured",
                    details={"enabled": enabled_channels},
                )

        except Exception as e:
            self._add_result(
                "channels",
                HealthStatus.DEGRADED,
                f"Failed to check channels: {e}",
            )

    def check_mcp_clients(self) -> None:
        """Check MCP client configurations."""
        try:
            from .utils import load_config
            from .validator import ConfigValidator

            config = load_config()
            result = ConfigValidator(config).validate_all()
            mcp_issues = [
                i for i in result.issues if i.path.startswith("mcp.")
            ]
            enabled_clients = [
                cid for cid, cfg in config.mcp.clients.items() if cfg.enabled
            ]

            if not enabled_clients:
                self._add_result(
                    "mcp_clients",
                    HealthStatus.HEALTHY,
                    "No MCP clients configured (optional)",
                    details={"enabled": 0},
                )
            elif mcp_issues:
                n_c = len(enabled_clients)
                n_i = len(mcp_issues)
                self._add_result(
                    "mcp_clients",
                    HealthStatus.DEGRADED,
                    f"{n_c} MCP client(s) enabled, but {n_i} have issues",
                    details={
                        "enabled": enabled_clients,
                        "issues": [
                            f"{i.path}: {i.message}" for i in mcp_issues
                        ],
                    },
                    suggestion=(
                        "Check MCP client configuration in config.json."
                    ),
                )
            else:
                n_c = len(enabled_clients)
                self._add_result(
                    "mcp_clients",
                    HealthStatus.HEALTHY,
                    f"{n_c} MCP client(s) properly configured",
                    details={"enabled": enabled_clients},
                )

        except Exception as e:
            self._add_result(
                "mcp_clients",
                HealthStatus.DEGRADED,
                f"Failed to check MCP clients: {e}",
            )

    def check_required_files(self) -> None:
        """Check if required Markdown files exist."""
        from ..constant import HEARTBEAT_FILE

        required_files = {
            "AGENTS.md": "Agent behavior configuration",
            HEARTBEAT_FILE: "Heartbeat query template",
            "MEMORY.md": "Memory management instructions",
            "SOUL.md": "Agent personality and values",
        }

        missing = []
        empty = []

        for filename, description in required_files.items():
            file_path = WORKING_DIR / filename
            if not file_path.exists():
                missing.append(f"{filename} ({description})")
            elif file_path.stat().st_size == 0:
                empty.append(f"{filename} ({description})")

        if missing:
            names = ", ".join(f.split(" ")[0] for f in missing)
            self._add_result(
                "required_files",
                HealthStatus.UNHEALTHY,
                f"Missing {len(missing)} required file(s): {names}",
                details={"missing": missing},
                suggestion="Run 'copaw init' to create missing files.",
            )
        elif empty:
            names = ", ".join(f.split(" ")[0] for f in empty)
            self._add_result(
                "required_files",
                HealthStatus.DEGRADED,
                f"{len(empty)} required file(s) are empty: {names}",
                details={"empty": empty},
                suggestion="Edit these files to configure agent behavior.",
            )
        else:
            self._add_result(
                "required_files",
                HealthStatus.HEALTHY,
                "All required files are present",
                details={"files": list(required_files.keys())},
            )

    def check_permissions(self) -> None:
        """Check working directory permissions."""
        import os

        critical_dirs = {
            "working_dir": WORKING_DIR,
            "active_skills": ACTIVE_SKILLS_DIR,
            "memory": WORKING_DIR / "memory",
            "file_store": WORKING_DIR / "file_store",
        }

        issues = []

        for name, dir_path in critical_dirs.items():
            if not dir_path.exists():
                continue
            if not os.access(dir_path, os.R_OK):
                issues.append(f"{name}: not readable")
            if not os.access(dir_path, os.W_OK):
                issues.append(f"{name}: not writable")

        if issues:
            self._add_result(
                "permissions",
                HealthStatus.UNHEALTHY,
                f"Permission issues in {len(issues)} location(s)",
                details={"issues": issues},
                suggestion=(
                    "Fix directory permissions with 'chmod'"
                    " or check file ownership."
                ),
            )
        else:
            self._add_result(
                "permissions",
                HealthStatus.HEALTHY,
                "All directories have proper permissions",
            )
