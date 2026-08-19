# -*- coding: utf-8 -*-
"""Tests for the Docker Hub runtime backend."""

import threading
import time
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.hub.docker_images import DockerImagePullStore
from qwenpaw.hub.docker_provisioner import DockerRuntimeProvisioner
from qwenpaw.hub.models import RuntimeRecord, RuntimeState


class _FakeImage:
    id = "sha256:resolved-image"
    short_id = "sha256:resolved"
    tags = ["docker.io/agentscope/qwenpaw:latest"]
    attrs = {
        "RepoDigests": ["docker.io/agentscope/qwenpaw@sha256:digest"],
        "Size": 123,
        "Created": "2026-08-19T00:00:00Z",
    }


class _FakeContainer:
    id = "container-a"
    status = "running"
    image = _FakeImage()
    attrs = {
        "Image": "sha256:resolved-image",
        "NetworkSettings": {
            "Ports": {"8088/tcp": [{"HostPort": "32123"}]},
        },
        "State": {"ExitCode": 0},
    }

    def reload(self) -> None:
        """Keep the static fake state."""

    def stop(self, timeout: int) -> None:
        del timeout
        self.status = "exited"

    def remove(self, force: bool) -> None:
        del force

    def logs(self, tail: int) -> bytes:
        del tail
        return b""


class _FakeContainers:
    def __init__(self) -> None:
        self.run_kwargs: dict[str, object] = {}
        self.container = _FakeContainer()

    def run(self, image: str, **kwargs: object) -> _FakeContainer:
        self.run_kwargs = {"image": image, **kwargs}
        return self.container

    def list(self, **kwargs: object) -> list[_FakeContainer]:
        del kwargs
        return []


class _FakeImages:
    def get(self, reference: str) -> _FakeImage:
        del reference
        return _FakeImage()

    def list(self) -> list[_FakeImage]:
        return [_FakeImage()]


class _FakeClient:
    def __init__(self) -> None:
        self.containers = _FakeContainers()
        self.images = _FakeImages()
        self.api = SimpleNamespace()

    def ping(self) -> bool:
        return True

    def info(self) -> dict[str, str]:
        return {"OSType": "linux"}


def _record(tmp_path: Path, metadata: dict | None = None) -> RuntimeRecord:
    root = tmp_path / "runtimes" / "runtime-a"
    return RuntimeRecord(
        runtime_id="runtime-a",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        provisioner="docker",
        host="127.0.0.1",
        port=0,
        state=RuntimeState.CREATED,
        working_dir=root / "working",
        secret_dir=root / "secrets",
        backup_dir=root / "backups",
        log_file=root / "logs" / "app.log",
        metadata=metadata or {},
    )


def _configure(provisioner: DockerRuntimeProvisioner) -> None:
    provisioner.configure(
        {
            "source": "docker_hub",
            "image": "docker.io/agentscope/qwenpaw:latest",
            "pull_policy": "if_not_present",
            "allowed_registries": ["docker.io"],
            "cpu_limit": 2.5,
            "memory_limit_mb": 3072,
            "pids_limit": 512,
            "shm_size_mb": 256,
        },
    )


def test_container_launch_applies_persistence_security_and_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    _configure(provisioner)
    monkeypatch.setattr(provisioner, "_wait_until_ready", lambda *_: None)

    running = provisioner.start(
        _record(tmp_path),
        {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "runtime-token"},
    )

    launch = client.containers.run_kwargs
    assert launch["image"] == "docker.io/agentscope/qwenpaw:latest"
    assert launch["nano_cpus"] == 2_500_000_000
    assert launch["mem_limit"] == "3072m"
    assert launch["pids_limit"] == 512
    assert launch["shm_size"] == "256m"
    assert launch["security_opt"] == ["no-new-privileges:true"]
    volumes = launch["volumes"]
    assert isinstance(volumes, dict)
    assert set(volumes) == {
        str(running.working_dir),
        str(running.secret_dir),
        str(running.backup_dir),
    }
    assert running.metadata["docker"]["image_id"] == ("sha256:resolved-image")


def test_pinned_runtime_uses_saved_image_id_after_policy_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    _configure(provisioner)
    monkeypatch.setattr(provisioner, "_wait_until_ready", lambda *_: None)
    record = _record(
        tmp_path,
        {
            "docker": {
                "image": "old.example.com/qwenpaw:v1",
                "pull_policy": "never",
                "image_id": "sha256:pinned-image",
                "image_digests": ["old.example.com/qwenpaw@sha256:one"],
            },
        },
    )

    provisioner.start(
        record,
        {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "runtime-token"},
    )

    assert client.containers.run_kwargs["image"] == "sha256:pinned-image"


def test_official_source_and_registry_validation_fail_closed(
    tmp_path: Path,
) -> None:
    provisioner = DockerRuntimeProvisioner(tmp_path, client=_FakeClient())

    with pytest.raises(ValueError, match="configured source"):
        provisioner.configure(
            {
                "source": "docker_hub",
                "image": "docker.io/example/qwenpaw:latest",
                "allowed_registries": ["docker.io"],
            },
        )

    with pytest.raises(ValueError, match="not allowed"):
        provisioner.configure(
            {
                "source": "custom",
                "image": "registry.example.com/qwenpaw:v1",
                "allowed_registries": ["docker.io"],
            },
        )


def test_readiness_requires_anonymous_rejection_and_token_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = DockerRuntimeProvisioner(
        tmp_path,
        start_timeout=0.1,
        client=_FakeClient(),
    )
    calls: list[str | urllib.request.Request] = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

    def urlopen(
        request: str | urllib.request.Request,
        timeout: int,
    ) -> _Response:
        del timeout
        calls.append(request)
        if isinstance(request, str):
            raise urllib.error.HTTPError(
                request,
                401,
                "Unauthorized",
                Message(),
                None,
            )
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    provisioner._wait_until_ready(  # pylint: disable=protected-access
        _record(tmp_path),
        "runtime-token",
    )

    assert len(calls) == 2
    token_request = calls[1]
    assert isinstance(token_request, urllib.request.Request)
    assert token_request.get_header("X-qwenpaw-runtime-token") == (
        "runtime-token"
    )


def test_pull_store_deduplicates_concurrent_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = DockerRuntimeProvisioner(tmp_path, client=_FakeClient())
    _configure(provisioner)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def pull(reference: str, progress) -> dict[str, object]:
        nonlocal calls
        del reference
        calls += 1
        started.set()
        release.wait(timeout=2)
        progress(100, "done")
        return {}

    monkeypatch.setattr(provisioner, "pull_image", pull)
    store = DockerImagePullStore(provisioner)
    try:
        first = store.submit("docker.io/agentscope/qwenpaw:latest")
        assert started.wait(timeout=1)
        second = store.submit("docker.io/agentscope/qwenpaw:latest")
        assert second.pull_id == first.pull_id
        release.set()
        deadline = time.monotonic() + 2
        while store.get(first.pull_id).status != "completed":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert calls == 1
    finally:
        release.set()
        store.close()
