# -*- coding: utf-8 -*-
"""Tests for the Docker Hub runtime backend."""

import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from email.message import Message
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.hub.docker_images import DockerImagePullStore
from qwenpaw.hub import docker_provisioner as docker_module
from qwenpaw.hub.docker_provisioner import DockerRuntimeProvisioner
from qwenpaw.hub.models import RuntimeState
from qwenpaw.hub.provisioner import RuntimeProvisioner
from tests.unit.hub.factories import runtime_record

_record = partial(runtime_record, provisioner="docker", port=0)


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
            "Ports": {
                "8088/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": "32123"},
                ],
            },
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
        network = SimpleNamespace(
            id="isolated-network",
            attrs={
                "Options": {"com.docker.network.bridge.enable_icc": "false"},
            },
        )
        self.networks = SimpleNamespace(get=lambda name: network)

    def ping(self) -> bool:
        return True

    def info(self) -> dict[str, str]:
        return {"OSType": "linux"}


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_desktop_model_access_uses_loopback_forwarding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    client = SimpleNamespace(
        info=lambda: {"OperatingSystem": "Docker Desktop"},
    )
    monkeypatch.setattr(
        docker_module,
        "sys",
        SimpleNamespace(platform=platform),
    )
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    assert provisioner.model_network().bind_host == "127.0.0.1"
    assert provisioner.model_network().url(43123) == (
        "http://host.docker.internal:43123"
    )


@pytest.mark.parametrize(
    "gateway",
    ["172.17.0.1", "192.168.40.1"],
)
def test_engine_model_access_uses_detected_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway: str,
) -> None:
    network = SimpleNamespace(
        attrs={
            "IPAM": {"Config": [{"Gateway": gateway}]},
            "Options": {"com.docker.network.bridge.enable_icc": "false"},
        },
    )
    client = SimpleNamespace(
        info=lambda: {"OperatingSystem": "Ubuntu"},
        networks=SimpleNamespace(get=lambda name: network),
    )
    monkeypatch.setattr(
        docker_module,
        "sys",
        SimpleNamespace(platform="linux"),
    )
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    assert provisioner.model_network().bind_host == gateway
    assert provisioner.model_network().url(43123) == f"http://{gateway}:43123"


@pytest.mark.parametrize(
    "gateway",
    ["0.0.0.0", "8.8.8.8", "224.0.0.1", "", "fd00::1"],
)
def test_engine_model_access_rejects_unusable_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway: str,
) -> None:
    network = SimpleNamespace(
        attrs={
            "IPAM": {"Config": [{"Gateway": gateway}]},
            "Options": {"com.docker.network.bridge.enable_icc": "false"},
        },
    )
    client = SimpleNamespace(
        info=lambda: {},
        networks=SimpleNamespace(get=lambda name: network),
    )
    monkeypatch.setattr(
        docker_module,
        "sys",
        SimpleNamespace(platform="linux"),
    )
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    with pytest.raises(RuntimeError, match="no private IPv4 gateway"):
        provisioner.model_network().url(43123)


def _configure(provisioner: DockerRuntimeProvisioner) -> None:
    provisioner.configure(
        {
            "source": "docker_hub",
            "image": "docker.io/agentscope/qwenpaw:latest",
            "pull_policy": "if_not_present",
            "cpu_limit": 2.5,
            "memory_limit_mb": 3072,
            "pids_limit": 512,
            "shm_size_mb": 256,
        },
    )


def test_close_does_not_connect_to_unused_docker_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client() -> None:
        raise AssertionError("close initialized the Docker client")

    monkeypatch.setattr("docker.from_env", unexpected_client)

    DockerRuntimeProvisioner(tmp_path).close()


def test_container_launch_applies_persistence_security_and_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    _configure(provisioner)
    monkeypatch.setattr(
        provisioner,
        "_wait_until_ready",
        lambda *_: "token",
    )

    running = provisioner.start(
        _record(
            tmp_path,
            metadata={"user_profile": {"workspace_dir": "/data/member"}},
        ),
        {
            "QWENPAW_RUNTIME_INTERNAL_TOKEN": "runtime-token",
            "QWENPAW_AUTH_ENABLED": "false",
            "PYTHONPATH": "/",
            "OPENAI_API_KEY": "tenant-key",
        },
    )

    launch = client.containers.run_kwargs
    assert launch["image"] == "docker.io/agentscope/qwenpaw:latest"
    assert launch["network"] == "isolated-network"
    assert launch["working_dir"] == "/data/member"
    assert launch["nano_cpus"] == 2_500_000_000
    assert launch["mem_limit"] == "3072m"
    assert launch["pids_limit"] == 512
    assert launch["shm_size"] == "256m"
    assert launch["security_opt"] == ["no-new-privileges:true"]
    environment = launch["environment"]
    assert isinstance(environment, dict)
    assert "PYTHONPATH" not in environment
    assert environment["HOME"] == "/data/member"
    assert environment["QWENPAW_WORKING_DIR"] == "/data/member"
    assert environment["OPENAI_API_KEY"] == "tenant-key"
    assert environment["QWENPAW_AUTH_ENABLED"] == "true"
    assert environment["QWENPAW_RUNTIME_INTERNAL_TOKEN"] == "runtime-token"
    volumes = launch["volumes"]
    assert isinstance(volumes, dict)
    assert set(volumes) == {
        str(running.working_dir),
        str(running.secret_dir),
        str(running.backup_dir),
    }
    assert volumes[str(running.working_dir)]["bind"] == "/data/member"
    assert running.metadata["docker"]["image_id"] == ("sha256:resolved-image")
    assert running.metadata["docker"]["boundary_mode"] == "token"


def test_pinned_runtime_uses_saved_image_id_after_policy_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    _configure(provisioner)
    monkeypatch.setattr(
        provisioner,
        "_wait_until_ready",
        lambda *_: "token",
    )
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


def test_official_source_validation_rejects_mismatched_image(
    tmp_path: Path,
) -> None:
    provisioner = DockerRuntimeProvisioner(tmp_path, client=_FakeClient())

    with pytest.raises(ValueError, match="configured source"):
        provisioner.configure(
            {
                "source": "docker_hub",
                "image": "docker.io/example/qwenpaw:latest",
            },
        )


def test_custom_source_accepts_qualified_and_local_image_tags(
    tmp_path: Path,
) -> None:
    provisioner = DockerRuntimeProvisioner(tmp_path, client=_FakeClient())

    provisioner.configure(
        {
            "source": "custom",
            "image": "registry.example.com/qwenpaw:v1",
        },
    )
    qualified = provisioner.validate_config({})
    local = provisioner.validate_config({"image": "qwenpaw-hub-e2e:test"})

    assert qualified["image"] == "registry.example.com/qwenpaw:v1"
    assert local["image"] == "qwenpaw-hub-e2e:test"


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

    result = provisioner._wait_until_ready(  # pylint: disable=protected-access
        _record(tmp_path),
        "runtime-token",
    )

    assert result == "token"
    assert len(calls) == 2
    assert str(calls[0]).endswith("/api/version")
    token_request = calls[1]
    assert isinstance(token_request, urllib.request.Request)
    assert token_request.get_header("X-qwenpaw-runtime-token") == (
        "runtime-token"
    )


def test_readiness_accepts_loopback_only_legacy_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = DockerRuntimeProvisioner(
        tmp_path,
        start_timeout=0.1,
        client=_FakeClient(),
    )

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(),
    )

    result = provisioner._wait_until_ready(  # pylint: disable=protected-access
        _record(tmp_path),
        "runtime-token",
    )

    assert result == "loopback_only"


def test_published_port_rejects_non_loopback_binding() -> None:
    container = _FakeContainer()
    container.attrs = {
        **container.attrs,
        "NetworkSettings": {
            "Ports": {
                "8088/tcp": [
                    {"HostIp": "0.0.0.0", "HostPort": "32123"},
                ],
            },
        },
    }

    with pytest.raises(RuntimeError, match="outside loopback"):
        # pylint: disable-next=protected-access
        DockerRuntimeProvisioner._published_port(
            container,
        )


def test_pull_store_deduplicates_image_from_another_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = DockerRuntimeProvisioner(tmp_path, client=_FakeClient())
    _configure(provisioner)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def pull(reference: str, **_kwargs):
        nonlocal calls
        assert reference == image
        calls += 1
        started.set()
        release.wait(timeout=2)
        yield {"status": "done"}

    image = f"{docker_module.ALIYUN_ACR_IMAGE}:latest"
    client = _FakeClient()
    client.api = SimpleNamespace(pull=pull)
    monkeypatch.setattr(provisioner, "_get_client", lambda: client)
    store = DockerImagePullStore(provisioner)
    try:
        first = store.submit(image)
        assert started.wait(timeout=1)
        second = store.submit(image)
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


def test_status_preserves_startup_failure_after_container_stops(
    tmp_path,
    monkeypatch,
):
    client = _FakeClient()
    client.containers.container.status = "exited"
    monkeypatch.setattr(
        client.containers,
        "list",
        lambda **kwargs: [client.containers.container],
    )
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    record = replace(
        _record(tmp_path),
        state=RuntimeState.FAILED,
        last_error="Runtime image is incompatible",
    )
    assert provisioner.status(record) == record


@pytest.mark.parametrize("status", [404, 200, 401])
def test_model_probe_allows_legacy_images_but_rejects_auth_errors(
    tmp_path,
    monkeypatch,
    status,
):
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            text="<html>Console</html>",
            headers={"content-type": "text/html"},
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.hub.provisioner.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    credentials = {
        "QWENPAW_HUB_MODEL_TOKEN": "model-token",
        "QWENPAW_RUNTIME_INTERNAL_TOKEN": "boundary-token",
    }
    if status == 401:
        with pytest.raises(RuntimeError, match="HTTP 401"):
            RuntimeProvisioner.verify_model_connection(
                _record(tmp_path),
                credentials,
            )
    else:
        RuntimeProvisioner.verify_model_connection(
            _record(tmp_path),
            credentials,
        )
