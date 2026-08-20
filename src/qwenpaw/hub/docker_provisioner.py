# -*- coding: utf-8 -*-
"""Docker-backed managed runtimes for QwenPaw Hub."""

from __future__ import annotations

import hashlib
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from .credentials import runtime_credential_name_allowed
from .models import RuntimeRecord, RuntimeState
from .provisioner import RuntimeProvisioner, RuntimeProvisionerAvailability

DOCKER_HUB_IMAGE = "docker.io/agentscope/qwenpaw"
ALIYUN_ACR_IMAGE = (
    "agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw"
)
DEFAULT_DOCKER_IMAGE = f"{DOCKER_HUB_IMAGE}:latest"
OFFICIAL_DOCKER_IMAGES = {
    "docker_hub": DOCKER_HUB_IMAGE,
    "aliyun_acr": ALIYUN_ACR_IMAGE,
}
OFFICIAL_DOCKER_TAGS = ("latest", "pre")
PULL_POLICIES = frozenset({"always", "if_not_present", "never"})

_IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}$")
_START_TIMEOUT_SECONDS = 90.0
_STOP_TIMEOUT_SECONDS = 20


class DockerRuntimeProvisioner(RuntimeProvisioner):
    """Run managed QwenPaw instances as Docker containers."""

    name = "docker"
    security_level = "isolated-container-shared-kernel"

    def __init__(
        self,
        root_dir: Path,
        *,
        start_timeout: float = _START_TIMEOUT_SECONDS,
        client: Any | None = None,
    ) -> None:
        self._root_dir = root_dir.resolve()
        self._start_timeout = start_timeout
        self._client = client
        self._client_lock = threading.RLock()
        self._policy: dict[str, object] = {}
        digest = hashlib.sha256(str(self._root_dir).encode("utf-8"))
        self._instance_id = digest.hexdigest()[:12]

    def configure(self, config: Mapping[str, object]) -> None:
        """Apply validated Docker defaults and resource limits."""
        previous = self._policy
        self._policy = dict(config)
        try:
            self.validate_config({})
        except ValueError:
            self._policy = previous
            raise

    def preflight(self, root_dir: Path) -> RuntimeProvisionerAvailability:
        """Verify that a Linux Docker engine is reachable."""
        root_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = self._get_client()
            client.ping()
            info = client.info()
            if str(info.get("OSType", "")).lower() != "linux":
                return RuntimeProvisionerAvailability(
                    available=False,
                    reason="Docker must be running Linux containers.",
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return RuntimeProvisionerAvailability(
                available=False,
                reason=str(exc),
            )
        return RuntimeProvisionerAvailability(available=True)

    def start(
        self,
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> RuntimeRecord:
        """Create a fresh container and wait for its protected API."""
        runtime_token = credentials.get("QWENPAW_RUNTIME_INTERNAL_TOKEN", "")
        if not runtime_token:
            raise RuntimeError(
                "Managed Docker runtime requires an internal boundary token.",
            )
        config = self.validate_config(record.metadata.get("docker", {}))
        image = str(config["image"])
        pull_policy = str(config["pull_policy"])
        image_id = str(config.get("image_id") or "")
        if image_id:
            if not self.image_exists(image_id):
                raise RuntimeError(
                    "The runtime's pinned Docker image is unavailable. "
                    "An administrator must rebuild the runtime.",
                )
            launch_image = image_id
        else:
            self._ensure_image(image, pull_policy)
            launch_image = image
        self._remove_containers(record.runtime_id)
        for path in (
            record.working_dir,
            record.secret_dir,
            record.backup_dir,
            record.log_file.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

        environment = {
            name: value
            for name, value in credentials.items()
            if runtime_credential_name_allowed(name)
        }
        environment.update(
            {
                "QWENPAW_WORKING_DIR": "/app/working",
                "QWENPAW_SECRET_DIR": "/app/working.secret",
                "QWENPAW_BACKUP_DIR": "/app/working.backups",
                "QWENPAW_RUNTIME_ID": record.runtime_id,
                "QWENPAW_TENANT_ID": record.tenant_id,
                "QWENPAW_RUNTIME_INTERNAL_TOKEN": runtime_token,
            },
        )
        labels = self._labels(record.runtime_id, record.owner_user_id)
        container = self._get_client().containers.run(
            launch_image,
            detach=True,
            environment=environment,
            init=True,
            labels=labels,
            name=self._container_name(record.runtime_id),
            ports={"8088/tcp": ("127.0.0.1", None)},
            restart_policy={"Name": "no"},
            security_opt=["no-new-privileges:true"],
            volumes={
                str(record.working_dir): {
                    "bind": "/app/working",
                    "mode": "rw",
                },
                str(record.secret_dir): {
                    "bind": "/app/working.secret",
                    "mode": "rw",
                },
                str(record.backup_dir): {
                    "bind": "/app/working.backups",
                    "mode": "rw",
                },
            },
            **self._resource_limits(),
        )
        try:
            port = self._published_port(container)
            starting = replace(
                record,
                host="127.0.0.1",
                port=port,
                state=RuntimeState.STARTING,
                pid=None,
                last_error=None,
                metadata=self._runtime_metadata(record, container),
            )
            boundary_mode = self._wait_until_ready(starting, runtime_token)
            container.reload()
            return replace(
                starting,
                state=RuntimeState.RUNNING,
                metadata=self._runtime_metadata(
                    starting,
                    container,
                    boundary_mode=boundary_mode,
                ),
            )
        except Exception:
            self._write_container_logs(record, container)
            try:
                container.stop(timeout=_STOP_TIMEOUT_SECONDS)
            except DockerException:
                pass
            raise

    def stop(self, record: RuntimeRecord) -> RuntimeRecord:
        """Stop and remove every container belonging to one runtime."""
        self._remove_containers(record.runtime_id)
        return replace(
            record,
            state=RuntimeState.STOPPED,
            pid=None,
            last_error=None,
        )

    def status(self, record: RuntimeRecord) -> RuntimeRecord:
        """Observe a managed container by immutable Hub labels."""
        containers = self._containers(record.runtime_id, all_containers=True)
        if not containers:
            if record.state in {RuntimeState.RUNNING, RuntimeState.STARTING}:
                return replace(
                    record,
                    state=RuntimeState.STOPPED,
                    pid=None,
                    last_error="Managed Docker container is not present.",
                )
            return record
        container = containers[0]
        container.reload()
        status = str(container.status)
        metadata = self._runtime_metadata(record, container)
        if status == "running":
            return replace(
                record,
                state=RuntimeState.RUNNING,
                pid=None,
                last_error=None,
                metadata=metadata,
            )
        state = container.attrs.get("State", {})
        exit_code = state.get("ExitCode")
        return replace(
            record,
            state=(
                RuntimeState.FAILED
                if exit_code not in {None, 0}
                else RuntimeState.STOPPED
            ),
            pid=None,
            last_error=(
                f"Docker container exited with code {exit_code}."
                if exit_code not in {None, 0}
                else None
            ),
            metadata=metadata,
        )

    def close(self) -> None:
        """Stop containers owned by this Hub instance."""
        if self._client is None:
            return
        for container in self._containers(all_containers=True):
            self._stop_and_remove(container)

    def validate_config(self, value: object) -> dict[str, object]:
        """Normalize and validate Docker-specific runtime configuration."""
        config = value if isinstance(value, Mapping) else {}
        default_image = self._policy.get("image", DEFAULT_DOCKER_IMAGE)
        default_policy = self._policy.get("pull_policy", "if_not_present")
        image = str(config.get("image", default_image)).strip()
        pull_policy = str(config.get("pull_policy", default_policy)).strip()
        pinned_image_id = config.get("image_id")
        if not _IMAGE_PATTERN.fullmatch(image):
            raise ValueError("Invalid Docker image reference.")
        if pull_policy not in PULL_POLICIES:
            raise ValueError("Invalid Docker image pull policy.")
        if not pinned_image_id:
            source = str(self._policy.get("source", "docker_hub"))
            if source in OFFICIAL_DOCKER_IMAGES:
                repository = OFFICIAL_DOCKER_IMAGES[source]
                if not (
                    image.startswith(f"{repository}:")
                    or image.startswith(f"{repository}@")
                ):
                    raise ValueError(
                        "Docker image does not match configured source: "
                        f"{source}",
                    )
            elif source != "custom":
                raise ValueError("Invalid Docker image source.")
        normalized: dict[str, object] = {
            "image": image,
            "pull_policy": pull_policy,
        }
        if pinned_image_id:
            normalized["image_id"] = str(pinned_image_id)
            normalized["image_digests"] = [
                str(item) for item in config.get("image_digests", [])
            ]
        return normalized

    @staticmethod
    def is_official_image(reference: str) -> bool:
        """Return whether a reference uses an official QwenPaw repository."""
        return any(
            reference == repository
            or reference.startswith(f"{repository}:")
            or reference.startswith(f"{repository}@")
            for repository in OFFICIAL_DOCKER_IMAGES.values()
        )

    def list_images(self) -> list[dict[str, object]]:
        """Return local Docker images as stable API records."""
        records: list[dict[str, object]] = []
        for image in self._get_client().images.list():
            attrs = image.attrs
            size = int(attrs.get("Size") or 0)
            tags = list(image.tags) or [f"{image.short_id}@untagged"]
            digests = list(attrs.get("RepoDigests") or [])
            for tag in tags:
                records.append(
                    {
                        "reference": tag,
                        "image_id": image.id,
                        "short_id": image.short_id,
                        "digests": digests,
                        "size": size,
                        "created": attrs.get("Created"),
                        "downloaded": True,
                    },
                )
        return sorted(records, key=lambda item: str(item["reference"]))

    def image_exists(self, reference: str) -> bool:
        """Return whether an exact image reference is available locally."""
        try:
            self._get_client().images.get(reference)
        except ImageNotFound:
            return False
        return True

    def pull_image(
        self,
        reference: str,
        progress: Callable[[int, str], None] | None = None,
    ) -> dict[str, object]:
        """Pull one image while reporting best-effort layer progress."""
        normalized = str(
            self.validate_config({"image": reference})["image"],
        )
        layers: dict[str, tuple[int, int]] = {}
        message = "Starting image pull"
        for event in self._get_client().api.pull(
            normalized,
            stream=True,
            decode=True,
        ):
            if event.get("error"):
                raise RuntimeError(str(event["error"]))
            layer_id = str(event.get("id") or "")
            detail = event.get("progressDetail") or {}
            current = int(detail.get("current") or 0)
            total = int(detail.get("total") or 0)
            if layer_id and total:
                layers[layer_id] = (current, total)
            message = str(event.get("status") or message)
            current_sum = sum(item[0] for item in layers.values())
            total_sum = sum(item[1] for item in layers.values())
            percent = int(current_sum * 100 / total_sum) if total_sum else 0
            if progress:
                progress(min(percent, 99), message)
        image = self._get_client().images.get(normalized)
        if progress:
            progress(100, "Image pull complete")
        return {
            "reference": normalized,
            "image_id": image.id,
            "digests": list(image.attrs.get("RepoDigests") or []),
            "size": int(image.attrs.get("Size") or 0),
            "downloaded": True,
        }

    def _get_client(self) -> Any:
        with self._client_lock:
            if self._client is None:
                self._client = docker.from_env()
            return self._client

    def _ensure_image(self, image: str, pull_policy: str) -> None:
        if pull_policy == "always":
            self.pull_image(image)
            return
        if self.image_exists(image):
            return
        if pull_policy == "never":
            raise RuntimeError(f"Docker image is not downloaded: {image}")
        self.pull_image(image)

    def _resource_limits(self) -> dict[str, object]:
        limits: dict[str, object] = {
            "shm_size": (f"{int(str(self._policy.get('shm_size_mb', 512)))}m"),
        }
        cpu_limit = self._policy.get("cpu_limit")
        memory_limit = self._policy.get("memory_limit_mb")
        pids_limit = self._policy.get("pids_limit")
        if cpu_limit is not None:
            limits["nano_cpus"] = int(
                float(str(cpu_limit)) * 1_000_000_000,
            )
        if memory_limit is not None:
            limits["mem_limit"] = f"{int(str(memory_limit))}m"
        if pids_limit is not None:
            limits["pids_limit"] = int(str(pids_limit))
        return limits

    def _containers(
        self,
        runtime_id: str | None = None,
        *,
        all_containers: bool = False,
    ) -> list[Any]:
        filters = {"label": [f"io.qwenpaw.hub.instance={self._instance_id}"]}
        if runtime_id:
            filters["label"].append(
                f"io.qwenpaw.hub.runtime-id={runtime_id}",
            )
        return list(
            self._get_client().containers.list(
                all=all_containers,
                filters=filters,
            ),
        )

    def _remove_containers(self, runtime_id: str) -> None:
        for container in self._containers(runtime_id, all_containers=True):
            self._stop_and_remove(container)

    @staticmethod
    def _stop_and_remove(container: Any) -> None:
        try:
            container.reload()
            if container.status == "running":
                container.stop(timeout=_STOP_TIMEOUT_SECONDS)
            container.remove(force=True)
        except NotFound:
            return

    def _labels(self, runtime_id: str, owner_user_id: str) -> dict[str, str]:
        return {
            "io.qwenpaw.hub.managed": "true",
            "io.qwenpaw.hub.instance": self._instance_id,
            "io.qwenpaw.hub.runtime-id": runtime_id,
            "io.qwenpaw.hub.owner-id": owner_user_id,
        }

    def _container_name(self, runtime_id: str) -> str:
        return f"qwenpaw-hub-{self._instance_id}-{runtime_id}"

    @staticmethod
    def _published_port(container: Any) -> int:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            container.reload()
            bindings = (
                container.attrs.get("NetworkSettings", {})
                .get(
                    "Ports",
                    {},
                )
                .get("8088/tcp")
            )
            if bindings:
                host_ip = str(bindings[0].get("HostIp") or "")
                if host_ip not in {"127.0.0.1", "::1"}:
                    raise RuntimeError(
                        "Docker published the runtime outside loopback: "
                        f"{host_ip or 'unknown'}",
                    )
                return int(bindings[0]["HostPort"])
            time.sleep(0.1)
        raise RuntimeError("Docker did not publish the runtime port.")

    @staticmethod
    def _runtime_metadata(
        record: RuntimeRecord,
        container: Any,
        *,
        boundary_mode: str | None = None,
    ) -> dict[str, Any]:
        image = container.attrs.get("Image", "")
        metadata = dict(record.metadata)
        docker_config = dict(metadata.get("docker", {}))
        docker_config.update(
            {
                "container_id": container.id,
                "image_id": image,
                "image_digests": list(
                    container.image.attrs.get("RepoDigests") or [],
                ),
            },
        )
        if boundary_mode is not None:
            docker_config["boundary_mode"] = boundary_mode
        metadata["docker"] = docker_config
        return metadata

    def _wait_until_ready(
        self,
        record: RuntimeRecord,
        runtime_token: str,
    ) -> str:
        deadline = time.monotonic() + self._start_timeout
        url = f"http://{record.host}:{record.port}/api/version"
        last_error = "readiness endpoint was not reachable"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if 200 <= response.status < 300:
                        return "loopback_only"
                    last_error = (
                        f"readiness endpoint returned {response.status}"
                    )
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    last_error = f"unexpected anonymous status {exc.code}"
                else:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "X-QwenPaw-Runtime-Token": runtime_token,
                        },
                    )
                    try:
                        with urllib.request.urlopen(
                            request,
                            timeout=2,
                        ) as response:
                            if 200 <= response.status < 300:
                                return "token"
                            last_error = (
                                f"readiness endpoint returned "
                                f"{response.status}"
                            )
                    except (OSError, urllib.error.URLError) as token_exc:
                        last_error = str(token_exc)
            except (OSError, urllib.error.URLError) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        raise RuntimeError(
            f"Docker runtime {record.runtime_id} failed security readiness: "
            f"{last_error}",
        )

    @staticmethod
    def _write_container_logs(record: RuntimeRecord, container: Any) -> None:
        try:
            output = container.logs(tail=200).decode("utf-8", errors="replace")
            with record.log_file.open("a", encoding="utf-8") as log_file:
                log_file.write(output)
        except (DockerException, OSError):
            return
