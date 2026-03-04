# -*- coding: utf-8 -*-
"""System health checks for CoPaw."""
from __future__ import annotations

import importlib
import logging
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
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
    details: dict = None
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
        return sum(1 for c in self.checks if c.status == HealthStatus.UNHEALTHY)


class HealthChecker:
    """Performs system health checks."""

    def __init__(self):
        self.results: list[HealthCheckResult] = []

    def check_all(self, test_connection: bool = False) -> SystemHealth:
        """Run all health checks.

        Args:
            test_connection: If True, test LLM API connection (slower).
        """
        self.results = []

        self.check_config_files()
        self.check_providers(test_connection=test_connection)
        self.check_skills()
        self.check_dependencies()
        self.check_environment()
        self.check_disk_space()

        # Determine overall status
        if any(r.status == HealthStatus.UNHEALTHY for r in self.results):
            overall = HealthStatus.UNHEALTHY
        elif any(r.status == HealthStatus.DEGRADED for r in self.results):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return SystemHealth(status=overall, checks=self.results)

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
            )
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
                suggestion="Check config.json syntax or run 'copaw init --force'.",
            )

    def check_providers(self, test_connection: bool = False) -> None:
        """Check if LLM providers are configured.

        Args:
            test_connection: If True, actually test the API connection.
        """
        try:
            from ..providers import load_providers_json
            from ..providers.registry import PROVIDERS

            data = load_providers_json()

            if not data.active_llm.provider_id or not data.active_llm.model:
                self._add_result(
                    "providers",
                    HealthStatus.UNHEALTHY,
                    "No active LLM configured",
                    suggestion="Run 'copaw models' to configure a model.",
                )
                return

            defn = PROVIDERS.get(data.active_llm.provider_id)

            if not defn:
                self._add_result(
                    "providers",
                    HealthStatus.UNHEALTHY,
                    f"Active provider '{data.active_llm.provider_id}' not found",
                    suggestion="Run 'copaw models' to select a valid provider.",
                )
                return

            if not data.is_configured(defn):
                self._add_result(
                    "providers",
                    HealthStatus.UNHEALTHY,
                    f"Provider '{defn.name}' is not configured",
                    suggestion=f"Configure {defn.name} API key via 'copaw models'.",
                )
                return

            # Test connection if requested
            if test_connection:
                connection_ok = self._test_llm_connection(
                    data.active_llm.provider_id,
                    data.active_llm.model
                )
                if not connection_ok:
                    self._add_result(
                        "providers",
                        HealthStatus.DEGRADED,
                        f"Provider configured but connection test failed: {defn.name} / {data.active_llm.model}",
                        details={
                            "provider": data.active_llm.provider_id,
                            "model": data.active_llm.model,
                        },
                        suggestion="Check API key, network connection, and API endpoint availability.",
                    )
                    return

            self._add_result(
                "providers",
                HealthStatus.HEALTHY,
                f"Active LLM: {defn.name} / {data.active_llm.model}"
                + (" (connection verified)" if test_connection else ""),
                details={
                    "provider": data.active_llm.provider_id,
                    "model": data.active_llm.model,
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
                suggestion="Run 'copaw init' or 'copaw skills config' to enable skills.",
            )
            return

        skill_count = sum(1 for d in skills_dir.iterdir()
                         if d.is_dir() and (d / "SKILL.md").exists())

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

        # Check Python version
        py_version = sys.version_info
        if py_version < (3, 10):
            issues.append(f"Python {py_version.major}.{py_version.minor} "
                         f"(requires >= 3.10)")

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
                    "python_version": f"{py_version.major}.{py_version.minor}.{py_version.micro}",
                    "platform": sys.platform,
                },
            )

    def check_disk_space(self) -> None:
        """Check available disk space in working directory."""
        try:
            stat = shutil.disk_usage(WORKING_DIR)
            free_gb = stat.free / (1024 ** 3)

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

    def _test_llm_connection(self, provider_id: str, model: str) -> bool:
        """Test LLM API connection with a simple request.

        Args:
            provider_id: Provider ID (e.g., 'dashscope', 'openai')
            model: Model name

        Returns:
            True if connection successful, False otherwise
        """
        try:
            from ..agents.model_factory import create_model

            # Create model instance
            model_instance = create_model(
                model_name=model,
                provider_id=provider_id,
            )

            # Try a minimal completion request
            response = model_instance(
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )

            # If we got here without exception, connection works
            return True

        except Exception as e:
            logger.debug(f"LLM connection test failed: {e}")
            return False
