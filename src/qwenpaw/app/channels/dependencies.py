# -*- coding: utf-8 -*-
"""Detection and background installation of built-in channel dependencies."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import importlib
from importlib.metadata import PackageNotFoundError, requires, version
import json
import logging
import os
from pathlib import Path
import platform
import re
import site
import subprocess
import sys
import tempfile
import threading
import tomllib
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from packaging.requirements import Requirement
import psutil

from ...constant import WORKING_DIR
from ...plugins.loader import (
    PluginLoader,
    _desktop_python,
    _is_frozen,
)
from ...plugins.install_lock import plugin_install_lock
from .catalog import BUILTIN_CHANNEL_CATALOG, ChannelSpec

logger = logging.getLogger(__name__)

_SOURCE_URLS = {
    "pypi": "https://pypi.org/simple/",
    "aliyun": "https://mirrors.aliyun.com/pypi/simple/",
}
_NETWORK_FAILURE_MARKERS = (
    "connection broken",
    "connection error",
    "connection reset",
    "connection refused",
    "connect timeout",
    "could not fetch url",
    "failed to establish a new connection",
    "nodename nor servname provided",
    "read timed out",
    "remote end closed connection",
    "retrying",
    "temporary failure in name resolution",
    "name or service not known",
    "network is unreachable",
    "proxyerror",
    "sslerror",
    "certificate verify failed",
    "too many 5",
    "http error 429",
    "http error 403",
    "http error 404",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
    "bad gateway",
    "service unavailable",
)
_MISSING_DISTRIBUTION_MARKERS = (
    "no matching distribution found",
    "could not find a version that satisfies the requirement",
)
_INCOMPATIBILITY_MARKERS = (
    "requires-python",
    "require a different python",
    "requires a different python",
    "not a supported wheel",
    "unsupported platform",
    "is not compatible with this python",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_url_credentials(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(
        r"(?P<scheme>https?://)[^/@\s]+@(?P<host>[^/\s]+)",
        r"\g<scheme><redacted>@\g<host>",
        value,
        flags=re.IGNORECASE,
    )


def _safe_source_label(value: str) -> str:
    if value in {"pypi", "aliyun"} or value.startswith(
        "custom:",
    ):
        return value
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        for name, url in _SOURCE_URLS.items():
            if parsed.hostname == urlsplit(url).hostname:
                return name
        return f"custom:{parsed.hostname}"
    return "custom:configured"


def _runtime_bucket() -> str:
    return (
        f"py{sys.version_info.major}.{sys.version_info.minor}"
        f"-{platform.system().lower()}-{platform.machine().lower()}"
    )


def _channel_site_dir() -> Path:
    return Path(WORKING_DIR) / "channel_runtime" / _runtime_bucket() / "site"


def _channel_state_dir() -> Path:
    if _is_frozen():
        environment = f"desktop-{_runtime_bucket()}"
    else:
        executable = str(Path(sys.executable).resolve())
        digest = hashlib.sha256(executable.encode("utf-8")).hexdigest()[:12]
        environment = f"python-{_runtime_bucket()}-{digest}"
    return Path(WORKING_DIR) / "channel_runtime" / "environments" / environment


def _ensure_channel_site_on_path() -> None:
    if not _is_frozen():
        value = str(_channel_site_dir())
        sys.path[:] = [entry for entry in sys.path if entry != value]
        return
    path = _channel_site_dir()
    if not path.exists():
        return
    value = str(path)
    site.addsitedir(value)
    if value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)
    importlib.invalidate_caches()


@lru_cache(maxsize=None)
def _source_pyproject_for(module_file: str) -> Path | None:
    for parent in Path(module_file).resolve().parents:
        candidate = parent / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if data.get("project", {}).get("name") == "qwenpaw":
            return candidate
    return None


def _source_pyproject() -> Path | None:
    return _source_pyproject_for(__file__)


@lru_cache(maxsize=None)
def _requirements_from_metadata(extra: str) -> list[str]:
    try:
        values = requires("qwenpaw") or []
    except PackageNotFoundError:
        return []
    result: list[str] = []
    for raw in values:
        req = Requirement(raw)
        if req.marker is None or not req.marker.evaluate({"extra": extra}):
            continue
        rendered = req.name
        if req.extras:
            rendered += "[" + ",".join(sorted(req.extras)) + "]"
        rendered += str(req.specifier)
        if req.url:
            rendered += f" @ {req.url}"
        result.append(rendered)
    return result


@lru_cache(maxsize=None)
def _requirements_for_extra_cached(
    extra: str,
    pyproject_path: str | None,
) -> tuple[str, ...]:
    if pyproject_path is not None:
        data = tomllib.loads(Path(pyproject_path).read_text(encoding="utf-8"))
        values = (
            data.get("project", {}).get("optional-dependencies", {}).get(extra)
        )
        if isinstance(values, list):
            return tuple(str(value) for value in values)
    return tuple(_requirements_from_metadata(extra))


def requirements_for_extra(extra: str | None) -> list[str]:
    """Return requirements for an extra, preferring source metadata in dev."""
    if not extra:
        return []
    pyproject = _source_pyproject()
    return list(
        _requirements_for_extra_cached(
            extra,
            str(pyproject) if pyproject is not None else None,
        ),
    )


def _requirement_applies(raw: str) -> bool:
    req = Requirement(raw)
    return req.marker is None or req.marker.evaluate()


def _is_requirement_satisfied(req: Requirement) -> bool:
    if _is_frozen():
        return PluginLoader.is_requirement_satisfied(req)
    try:
        installed = version(req.name)
    except PackageNotFoundError:
        return False
    return not req.specifier or req.specifier.contains(installed)


def missing_requirements(spec: ChannelSpec) -> list[str]:
    """Return only requirements missing or outside the supported version."""
    _ensure_channel_site_on_path()
    missing: list[str] = []
    for raw in requirements_for_extra(spec.extra):
        req = Requirement(raw)
        if _requirement_applies(
            raw,
        ) and not _is_requirement_satisfied(req):
            missing.append(raw)
    return missing


@dataclass
class InstallJob:
    id: str
    channel: str
    requirements: list[str]
    source: str = "aliyun"
    custom_index_url: str | None = None
    reinstall: bool = False
    status: str = "queued"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    error: str | None = None
    attempted_sources: list[str] = field(default_factory=list)
    owner_pid: int | None = None
    owner_started_at: float | None = None

    def storage_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("custom_index_url", None)
        data["attempted_sources"] = [
            _safe_source_label(value) for value in self.attempted_sources
        ]
        data["error"] = _redact_url_credentials(self.error)
        return data

    def public_dict(self) -> dict[str, Any]:
        data = self.storage_dict()
        data.pop("owner_pid", None)
        data.pop("owner_started_at", None)
        return data


class ChannelDependencyService:
    """Cross-process dependency status cache and install job manager."""

    def __init__(self) -> None:
        self._jobs: dict[str, InstallJob] = {}
        self._active_by_channel: dict[str, str] = {}
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._state_dir = _channel_state_dir()
        self._load_jobs()

    def _load_jobs(self) -> None:
        try:
            self._refresh_jobs_from_disk()
        except Exception:
            logger.warning(
                "Failed to restore channel dependency jobs",
                exc_info=True,
            )
            self._jobs.clear()
            self._active_by_channel.clear()

    def channel_status(
        self,
        key: str,
        *,
        refresh: bool = True,
    ) -> dict[str, Any]:
        if refresh:
            self._refresh_jobs_from_disk()
        spec = BUILTIN_CHANNEL_CATALOG[key]
        if not spec.platform_supported:
            return {
                "channel": key,
                "status": "platform_unsupported",
                "platforms": sorted(spec.platforms or ()),
                "requirements": requirements_for_extra(spec.extra),
                "missing_requirements": [],
            }
        with self._lock:
            job_id = self._active_by_channel.get(key)
            current = self._jobs.get(job_id) if job_id else None
            job = replace(current) if current else None
            if job:
                job.requirements = list(job.requirements)
                job.attempted_sources = list(job.attempted_sources)
        if job and job.status in {"queued", "installing", "verifying"}:
            return {
                "channel": key,
                "status": "installing",
                "job_id": job.id,
                "requirements": requirements_for_extra(spec.extra),
                "missing_requirements": list(job.requirements),
            }
        missing = missing_requirements(spec)
        status = (
            "failed"
            if missing and job and job.status == "failed"
            else "missing"
            if missing
            else "ready"
        )
        error = None
        if not missing:
            try:
                module = importlib.import_module(
                    spec.module,
                    package=__package__,
                )
                getattr(module, spec.class_name)
            except Exception as exc:
                status = "load_error"
                error = f"{type(exc).__name__}: {exc}"
        result: dict[str, Any] = {
            "channel": key,
            "status": status,
            "requirements": requirements_for_extra(spec.extra),
            "missing_requirements": missing,
        }
        if error:
            result["error"] = error
        if job and job.status == "failed":
            result["last_job_id"] = job.id
            result["last_error"] = job.error
        return result

    def all_statuses(self) -> dict[str, dict[str, Any]]:
        self._refresh_jobs_from_disk()
        result: dict[str, dict[str, Any]] = {}
        for key, spec in BUILTIN_CHANNEL_CATALOG.items():
            try:
                result[key] = self.channel_status(key, refresh=False)
            except Exception as exc:
                logger.exception(
                    "Failed to inspect channel dependencies: %s",
                    key,
                )
                result[key] = {
                    "channel": key,
                    "status": "load_error",
                    "requirements": requirements_for_extra(spec.extra),
                    "missing_requirements": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
        return result

    def get_job(self, job_id: str) -> InstallJob | None:
        self._refresh_jobs_from_disk()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            snapshot = replace(job)
            snapshot.requirements = list(job.requirements)
            snapshot.attempted_sources = list(job.attempted_sources)
            return snapshot

    async def start_install(
        self,
        channel: str,
        *,
        source: str = "aliyun",
        custom_index_url: str | None = None,
        reinstall: bool = False,
        on_success: Callable[[], None] | None = None,
    ) -> InstallJob:
        spec = BUILTIN_CHANNEL_CATALOG[channel]
        if not spec.platform_supported:
            raise ValueError("Channel is not supported on this platform")
        missing = await asyncio.to_thread(missing_requirements, spec)
        if missing and reinstall:
            raise ValueError(
                "Reinstall is only available when Channel loading fails",
            )
        if not missing:
            if not reinstall:
                raise ValueError("Channel dependencies are already installed")
            error = await asyncio.to_thread(self._channel_load_error, spec)
            if error is None:
                raise ValueError("Channel is already ready")
            missing = await asyncio.to_thread(
                requirements_for_extra,
                spec.extra,
            )
            if not missing:
                raise ValueError("Channel has no reinstallable dependencies")
        job, created = await asyncio.to_thread(
            self._create_install_job,
            channel,
            missing,
            source=source,
            custom_index_url=custom_index_url,
            reinstall=reinstall,
        )
        if created:
            asyncio.create_task(self._run_job(job, on_success=on_success))
        return job

    def _create_install_job(
        self,
        channel: str,
        requirements: list[str],
        *,
        source: str,
        custom_index_url: str | None,
        reinstall: bool,
    ) -> tuple[InstallJob, bool]:
        with self._persist_lock, self._jobs_file_lock() as acquired:
            if not acquired:
                raise RuntimeError(
                    "Timed out waiting for channel job state lock",
                )
            jobs, changed = self._read_jobs_file()
            changed = self._mark_interrupted_jobs(jobs) or changed
            existing = self._latest_channel_job(jobs, channel)
            if existing and existing.status in {
                "queued",
                "installing",
                "verifying",
            }:
                if changed:
                    self._write_jobs_file(jobs)
                self._replace_cached_jobs(jobs)
                return replace(existing), False
            jobs = {
                job_id: saved
                for job_id, saved in jobs.items()
                if saved.channel != channel
            }
            job = InstallJob(
                id=uuid4().hex,
                channel=channel,
                requirements=requirements,
                source=source,
                custom_index_url=custom_index_url,
                reinstall=reinstall,
                owner_pid=os.getpid(),
                owner_started_at=psutil.Process().create_time(),
            )
            jobs[job.id] = job
            self._cancel_path(job.id).unlink(missing_ok=True)
            self._write_jobs_file(jobs)
            self._replace_cached_jobs(jobs, local_job=job)
        return job, True

    async def _run_job(
        self,
        job: InstallJob,
        *,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        await asyncio.to_thread(self._update_job, job, status="installing")
        try:
            await asyncio.to_thread(self._install_locked, job)
            await asyncio.to_thread(self._raise_if_cancelled, job)
            await asyncio.to_thread(self._update_job, job, status="verifying")
            remaining = await asyncio.to_thread(
                self._verify_channel,
                job.channel,
            )
            await asyncio.to_thread(self._raise_if_cancelled, job)
            if remaining:
                raise RuntimeError(
                    "Installation completed but dependencies are still "
                    "missing: " + ", ".join(remaining),
                )
            await asyncio.to_thread(self._raise_if_cancelled, job)
            await asyncio.to_thread(self._update_job, job, status="succeeded")
            if on_success is not None:
                try:
                    on_success()
                except Exception:
                    logger.exception(
                        "Post-install channel reload failed: %s",
                        job.channel,
                    )
        except Exception as exc:
            logger.exception(
                "Channel dependency installation failed: %s",
                job.channel,
            )
            await asyncio.to_thread(
                self._update_job,
                job,
                status="failed",
                error=str(exc)[-4000:],
            )
        finally:
            await asyncio.to_thread(
                self._cancel_path(job.id).unlink,
                missing_ok=True,
            )

    def _install_locked(self, job: InstallJob) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._state_dir / "install.lock"
        with plugin_install_lock(
            lock_path,
            timeout=660,
            cancel_checker=lambda: self._is_cancel_requested(job),
        ) as acquired:
            self._raise_if_cancelled(job)
            if not acquired:
                raise RuntimeError(
                    "Timed out waiting for another channel dependency install",
                )
            current = missing_requirements(
                BUILTIN_CHANNEL_CATALOG[job.channel],
            )
            if not current and not job.reinstall:
                return
            requirements = job.requirements if job.reinstall else current
            self._install_with_sources(
                job,
                requirements,
                reinstall=job.reinstall,
            )

    @staticmethod
    def _channel_load_error(spec: ChannelSpec) -> str | None:
        try:
            module = importlib.import_module(spec.module, package=__package__)
            getattr(module, spec.class_name)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return None

    @classmethod
    def _verify_channel(cls, channel: str) -> list[str]:
        importlib.invalidate_caches()
        _ensure_channel_site_on_path()
        from .registry import clear_builtin_channel_cache

        clear_builtin_channel_cache()
        spec = BUILTIN_CHANNEL_CATALOG[channel]
        remaining = missing_requirements(spec)
        if remaining:
            return remaining
        module_name = importlib.util.resolve_name(spec.module, __package__)
        sys.modules.pop(module_name, None)
        error = cls._channel_load_error(spec)
        if error is not None:
            raise RuntimeError(f"Channel failed to load: {error}")
        return []

    def _source_candidates(
        self,
        job: InstallJob,
    ) -> list[tuple[str | None, str]]:
        primary: tuple[str | None, str]
        if job.source == "custom":
            if not job.custom_index_url:
                raise ValueError(
                    "custom_index_url is required for custom source",
                )
            hostname = urlsplit(job.custom_index_url).hostname or "configured"
            primary = (job.custom_index_url, f"custom:{hostname}")
        elif job.source in _SOURCE_URLS:
            primary = (_SOURCE_URLS[job.source], job.source)
        else:
            raise ValueError(f"Unsupported package source: {job.source}")

        fallback_name = "pypi" if job.source == "aliyun" else "aliyun"
        return [primary, (_SOURCE_URLS[fallback_name], fallback_name)]

    def _install_with_sources(
        self,
        job: InstallJob,
        requirements: list[str],
        *,
        reinstall: bool = False,
    ) -> None:
        last_output = ""
        for index_url, label in self._source_candidates(job):
            self._raise_if_cancelled(job)
            self._append_attempted_source(job, label)
            try:
                result = self._run_install(
                    requirements,
                    index_url,
                    job.channel,
                    cancel_checker=lambda: self._is_cancel_requested(job),
                    reinstall=reinstall,
                )
            except subprocess.TimeoutExpired:
                last_output = f"Package source {label} timed out"
                continue
            if result.returncode == 0:
                return
            last_output = (
                result.stdout
                or result.stderr
                or "dependency installation failed"
            )
            if not self._should_fallback(last_output, label):
                break
        raise RuntimeError(last_output[-4000:])

    @staticmethod
    def _should_fallback(output: str, source: str) -> bool:
        lowered = output.lower()
        if any(marker in lowered for marker in _INCOMPATIBILITY_MARKERS):
            return False
        if source == "pypi" and "http error 404" in lowered:
            return False
        if any(marker in lowered for marker in _NETWORK_FAILURE_MARKERS):
            return True
        return source != "pypi" and any(
            marker in lowered for marker in _MISSING_DISTRIBUTION_MARKERS
        )

    def _run_install(
        self,
        requirements: list[str],
        index_url: str | None,
        channel: str,
        *,
        cancel_checker: Callable[[], bool] | None = None,
        reinstall: bool = False,
    ) -> subprocess.CompletedProcess:
        redact_values: list[str] | None = None
        install_env: dict[str, str] | None = None
        if index_url:
            parsed = urlsplit(index_url)
            credential = ""
            if parsed.username is not None:
                credential = parsed.username
                if parsed.password is not None:
                    credential += f":{parsed.password}"
                credential += "@"
            redact_values = [
                value for value in (index_url, credential) if value
            ]
            # Keep credentials out of the process command line. Both pip and uv
            # honour these variables, and blank extra indexes prevent an
            # explicitly selected source from silently consulting another one.
            install_env = os.environ.copy()
            install_env.update(
                {
                    "PIP_INDEX_URL": index_url,
                    "UV_INDEX_URL": index_url,
                    "PIP_EXTRA_INDEX_URL": "",
                    "UV_EXTRA_INDEX_URL": "",
                },
            )
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".txt",
            encoding="utf-8",
            delete=False,
        ) as req_file:
            req_file.write("\n".join(requirements) + "\n")
            req_path = req_file.name
        try:
            if _is_frozen():
                python = _desktop_python()
                if python is None:
                    raise RuntimeError(
                        "Bundled desktop Python runtime is unavailable",
                    )
                cmd = [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--upgrade-strategy",
                    "only-if-needed",
                    "--upgrade",
                    "--target",
                    str(_channel_site_dir()),
                    "-r",
                    req_path,
                ]
            else:
                cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "-r",
                    req_path,
                ]
            if reinstall:
                cmd.insert(-2, "--force-reinstall")
            result = PluginLoader.run_subprocess_with_streaming_log(
                cmd,
                timeout=600,
                plugin_id=f"channel-{channel}",
                redact_values=redact_values,
                environment=install_env,
                cancel_checker=cancel_checker,
            )
            if (
                not _is_frozen()
                and result.returncode != 0
                and "No module named pip" in result.stdout
            ):
                uv = PluginLoader.find_uv()
                if uv:
                    cmd = [
                        uv,
                        "pip",
                        "install",
                        "--python",
                        sys.executable,
                        "-r",
                        req_path,
                    ]
                    if reinstall:
                        cmd.insert(-2, "--force-reinstall")
                    result = PluginLoader.run_subprocess_with_streaming_log(
                        cmd,
                        timeout=600,
                        plugin_id=f"channel-{channel}",
                        redact_values=redact_values,
                        environment=install_env,
                        cancel_checker=cancel_checker,
                    )
            return result
        finally:
            Path(req_path).unlink(missing_ok=True)

    def cancel_install(self, channel: str) -> InstallJob:
        self._refresh_jobs_from_disk()
        with self._lock:
            job_id = self._active_by_channel.get(channel)
            current = self._jobs.get(job_id) if job_id else None
            if current is None or current.status not in {
                "queued",
                "installing",
                "verifying",
            }:
                raise ValueError(
                    "Channel dependency installation is not active",
                )
            job = replace(current)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        cancel_path = self._cancel_path(job.id)
        cancel_path.parent.mkdir(parents=True, exist_ok=True)
        cancel_path.touch()
        return job

    def _cancel_path(self, job_id: str) -> Path:
        return self._state_dir / "cancel" / job_id

    def _is_cancel_requested(self, job: InstallJob) -> bool:
        return self._cancel_path(job.id).is_file()

    def _raise_if_cancelled(self, job: InstallJob) -> None:
        if self._is_cancel_requested(job):
            raise RuntimeError("Dependency installation was stopped by user")

    def _jobs_file_lock(self):
        self._state_dir.mkdir(parents=True, exist_ok=True)
        return plugin_install_lock(
            self._state_dir / "install_jobs.lock",
            timeout=30,
        )

    def _read_jobs_file(self) -> tuple[dict[str, InstallJob], bool]:
        path = self._state_dir / "install_jobs.json"
        if not path.is_file():
            return {}, False
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("install_jobs.json must contain a list")
        jobs: dict[str, InstallJob] = {}
        changed = False
        for raw in payload:
            if not isinstance(raw, dict):
                changed = True
                continue
            job = InstallJob(**raw)
            if job.source == "auto":
                job.source = "aliyun"
                changed = True
            safe_sources = [
                _safe_source_label(value) for value in job.attempted_sources
            ]
            safe_error = _redact_url_credentials(job.error)
            if (
                safe_sources != job.attempted_sources
                or safe_error != job.error
            ):
                job.attempted_sources = safe_sources
                job.error = safe_error
                changed = True
            jobs[job.id] = job
        return jobs, changed

    @staticmethod
    def _pid_is_running(pid: int | None, started_at: float | None) -> bool:
        if pid is None or pid <= 0 or started_at is None:
            return False
        try:
            return abs(psutil.Process(pid).create_time() - started_at) < 1.0
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            # A matching live PID with inaccessible metadata is safer to keep
            # active than to launch a concurrent install into the same target.
            return psutil.pid_exists(pid)

    def _mark_interrupted_jobs(self, jobs: dict[str, InstallJob]) -> bool:
        changed = False
        for job in jobs.values():
            if job.status not in {"queued", "installing", "verifying"}:
                continue
            if self._pid_is_running(job.owner_pid, job.owner_started_at):
                continue
            job.status = "failed"
            job.error = "Installation was interrupted by a QwenPaw restart"
            job.updated_at = _utc_now()
            changed = True
        return changed

    @staticmethod
    def _latest_channel_job(
        jobs: dict[str, InstallJob],
        channel: str,
    ) -> InstallJob | None:
        candidates = [job for job in jobs.values() if job.channel == channel]
        return max(candidates, key=lambda job: job.updated_at, default=None)

    def _replace_cached_jobs(
        self,
        jobs: dict[str, InstallJob],
        *,
        local_job: InstallJob | None = None,
    ) -> None:
        cached = {job_id: replace(job) for job_id, job in jobs.items()}
        if local_job is not None:
            cached[local_job.id] = local_job
        active: dict[str, str] = {}
        for job in cached.values():
            current = cached.get(active.get(job.channel, ""))
            if current is None or job.updated_at >= current.updated_at:
                active[job.channel] = job.id
        with self._lock:
            self._jobs = cached
            self._active_by_channel = active

    def _write_jobs_file(self, jobs: dict[str, InstallJob]) -> None:
        path = self._state_dir / "install_jobs.json"
        payload = [job.storage_dict() for job in jobs.values()]
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    def _refresh_jobs_from_disk(self) -> None:
        if not (self._state_dir / "install_jobs.json").is_file():
            return
        with self._persist_lock, self._jobs_file_lock() as acquired:
            if not acquired:
                raise RuntimeError(
                    "Timed out waiting for channel job state lock",
                )
            jobs, changed = self._read_jobs_file()
            changed = self._mark_interrupted_jobs(jobs) or changed
            if changed:
                self._write_jobs_file(jobs)
        self._replace_cached_jobs(jobs)

    def _persist_job(self, job: InstallJob) -> None:
        with self._persist_lock, self._jobs_file_lock() as acquired:
            if not acquired:
                raise RuntimeError(
                    "Timed out waiting for channel job state lock",
                )
            jobs, _ = self._read_jobs_file()
            jobs[job.id] = replace(job)
            self._write_jobs_file(jobs)
        self._replace_cached_jobs(jobs, local_job=job)

    def _update_job(self, job: InstallJob, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = _utc_now()
        self._persist_job(job)

    def _append_attempted_source(self, job: InstallJob, label: str) -> None:
        with self._lock:
            job.attempted_sources.append(label)
            job.updated_at = _utc_now()
        self._persist_job(job)


channel_dependency_service = ChannelDependencyService()
