# -*- coding: utf-8 -*-
"""Tests for the Docker Hub runtime backend."""

import ipaddress
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
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
        host_ip = "127.0.0.1"
        ports = kwargs.get("ports")
        if isinstance(ports, dict):
            binding = ports.get("8088/tcp")
            if isinstance(binding, tuple) and binding:
                host_ip = str(binding[0])
        current = self.container.attrs
        self.container.attrs = {
            **current,
            "NetworkSettings": {
                "Ports": {
                    "8088/tcp": [
                        {"HostIp": host_ip, "HostPort": "32123"},
                    ],
                },
            },
        }
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


class _EndpointClient(_FakeClient):
    """Engine whose OS string and bridge gateway are fixed."""

    def __init__(
        self,
        operating_system: str,
        gateway: str | None,
    ) -> None:
        super().__init__()
        config: list[dict[str, str]] = []
        if gateway is not None:
            config = [{"Gateway": gateway}]
        network = SimpleNamespace(
            id="isolated-network",
            attrs={
                "IPAM": {"Config": config},
                "Options": {
                    "com.docker.network.bridge.enable_icc": "false",
                },
            },
        )
        self.networks = SimpleNamespace(get=lambda _name: network)
        self._operating_system = operating_system

    def info(self) -> dict[str, str]:
        return {
            "OSType": "linux",
            "OperatingSystem": self._operating_system,
        }


def _record_readiness_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Capture readiness URLs and accept the token boundary."""
    seen: list[str] = []

    class _Response:
        status = 200

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            del args

    def urlopen(
        request: str | urllib.request.Request,
        timeout: int,
    ) -> _Response:
        del timeout
        if isinstance(request, str):
            seen.append(request)
            raise urllib.error.HTTPError(
                request,
                401,
                "Unauthorized",
                Message(),
                None,
            )
        seen.append(request.full_url)
        return _Response()

    monkeypatch.setattr(docker_module, "_open_readiness", urlopen)
    return seen


def _route_table(gateway: str | None) -> str:
    """Build a /proc/net/route table with one optional default gateway."""
    header = (
        "Iface Destination Gateway Flags RefCnt Use Metric "
        "Mask MTU Window IRTT\n"
    )
    if gateway is None:
        return header
    packed = ipaddress.IPv4Address(gateway).packed[::-1].hex()
    return header + (f"eth0 00000000 {packed} 0003 0 0 0 00000000 0 0 0\n")


def _install_container_net(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    shares_netns: bool,
    container_gateway: str | None,
) -> None:
    """Point route and netns reads at a fixture instead of this host."""
    sys_net = tmp_path / "sys-class-net"
    sys_net.mkdir()
    interface = "docker0" if shares_netns else "eth0"
    (sys_net / interface).mkdir()
    route = tmp_path / "route"
    route.write_text(
        _route_table(container_gateway),
        encoding="utf-8",
    )
    monkeypatch.setattr(docker_module, "_SYS_CLASS_NET", sys_net)
    monkeypatch.setattr(docker_module, "_PROC_NET_ROUTE", route)


def _start_for_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    in_container: bool,
    platform: str,
    operating_system: str,
    gateway: str | None,
    shares_netns: bool = False,
    container_gateway: str | None = None,
) -> tuple[str, list[str], DockerRuntimeProvisioner]:
    """Launch one runtime and return its stored host and probe URLs."""
    monkeypatch.setattr(
        docker_module,
        "is_running_in_container",
        lambda: in_container,
        raising=False,
    )
    monkeypatch.setattr(
        docker_module,
        "sys",
        SimpleNamespace(platform=platform),
    )
    _install_container_net(
        tmp_path,
        monkeypatch,
        shares_netns=shares_netns,
        container_gateway=container_gateway,
    )
    seen = _record_readiness_urls(monkeypatch)
    client = _EndpointClient(operating_system, gateway)
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    _configure(provisioner)
    running = provisioner.start(
        _record(tmp_path),
        {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "runtime-token"},
    )
    return running.host, seen, provisioner


@pytest.mark.parametrize(
    ("platform", "operating_system", "gateway"),
    [
        ("linux", "Docker Desktop", "172.17.0.1"),
        ("linux", "Ubuntu", "172.17.0.1"),
        ("win32", "Docker Desktop", None),
    ],
)
def test_host_deployment_probes_published_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    operating_system: str,
    gateway: str | None,
) -> None:
    host, urls, provisioner = _start_for_endpoint(
        tmp_path,
        monkeypatch,
        in_container=False,
        platform=platform,
        operating_system=operating_system,
        gateway=gateway,
        container_gateway="172.18.0.1",
    )

    assert host == "127.0.0.1"
    assert urls == [
        "http://127.0.0.1:32123/api/version",
        "http://127.0.0.1:32123/api/version",
    ]
    # pylint: disable-next=protected-access
    ports = provisioner._client.containers.run_kwargs["ports"]
    assert ports == {"8088/tcp": ("127.0.0.1", None)}
    assert provisioner.managed_endpoint_allowed("127.0.0.1")
    assert not provisioner.managed_endpoint_allowed(
        "host.docker.internal",
    )
    assert not provisioner.managed_endpoint_allowed("192.0.2.10")
    assert not provisioner.managed_endpoint_allowed("172.18.0.1")
    if gateway is not None:
        assert not provisioner.managed_endpoint_allowed(gateway)


@pytest.mark.parametrize(
    (
        "platform",
        "operating_system",
        "model_gateway",
        "shares_netns",
        "container_gateway",
        "dial_host",
        "publish_host",
    ),
    [
        (
            "linux",
            "Docker Desktop",
            "172.17.0.1",
            False,
            "172.18.0.1",
            "host.docker.internal",
            "127.0.0.1",
        ),
        (
            "darwin",
            "Docker Desktop",
            None,
            False,
            None,
            "host.docker.internal",
            "127.0.0.1",
        ),
        (
            "linux",
            "Ubuntu",
            "172.17.0.1",
            True,
            "192.168.1.1",
            "127.0.0.1",
            "127.0.0.1",
        ),
        (
            "linux",
            "Ubuntu",
            "172.17.0.1",
            False,
            "172.18.0.1",
            "172.18.0.1",
            "172.18.0.1",
        ),
        (
            "linux",
            "Ubuntu",
            "192.168.40.1",
            False,
            "10.1.2.1",
            "10.1.2.1",
            "10.1.2.1",
        ),
    ],
)
def test_container_deployment_probes_reachable_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    operating_system: str,
    model_gateway: str | None,
    shares_netns: bool,
    container_gateway: str | None,
    dial_host: str,
    publish_host: str,
) -> None:
    resolved, urls, provisioner = _start_for_endpoint(
        tmp_path,
        monkeypatch,
        in_container=True,
        platform=platform,
        operating_system=operating_system,
        gateway=model_gateway,
        shares_netns=shares_netns,
        container_gateway=container_gateway,
    )

    assert resolved == dial_host
    assert urls == [
        f"http://{dial_host}:32123/api/version",
        f"http://{dial_host}:32123/api/version",
    ]
    # pylint: disable-next=protected-access
    ports = provisioner._client.containers.run_kwargs["ports"]
    assert ports == {"8088/tcp": (publish_host, None)}
    assert provisioner.managed_endpoint_allowed(dial_host)
    assert provisioner.managed_endpoint_allowed("127.0.0.1")
    assert not provisioner.managed_endpoint_allowed("192.0.2.10")
    assert not provisioner.managed_endpoint_allowed("10.0.0.8")
    if dial_host != "host.docker.internal":
        assert not provisioner.managed_endpoint_allowed(
            "host.docker.internal",
        )
    if model_gateway and model_gateway != dial_host:
        assert not provisioner.managed_endpoint_allowed(model_gateway)
    if container_gateway and container_gateway != dial_host:
        assert not provisioner.managed_endpoint_allowed(container_gateway)


@pytest.mark.parametrize(
    "gateway",
    [None, "8.8.8.8", "169.254.1.1"],
)
def test_bridge_container_does_not_publish_an_unreachable_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway: str | None,
) -> None:
    monkeypatch.setattr(
        docker_module,
        "is_running_in_container",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        docker_module,
        "sys",
        SimpleNamespace(platform="linux"),
    )
    _install_container_net(
        tmp_path,
        monkeypatch,
        shares_netns=False,
        container_gateway=gateway,
    )
    client = _EndpointClient("Ubuntu", "172.17.0.1")
    provisioner = DockerRuntimeProvisioner(tmp_path, client=client)
    _configure(provisioner)

    with pytest.raises(
        RuntimeError,
        match="private IPv4 default gateway",
    ):
        provisioner.start(
            _record(tmp_path),
            {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "runtime-token"},
        )

    assert client.containers.run_kwargs == {}


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

    monkeypatch.setattr(docker_module, "_open_readiness", urlopen)

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
        docker_module,
        "_open_readiness",
        lambda *_args, **_kwargs: _Response(),
    )

    result = provisioner._wait_until_ready(  # pylint: disable=protected-access
        _record(tmp_path),
        "runtime-token",
    )

    assert result == "loopback_only"


def test_readiness_rejects_anonymous_success_on_gateway_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An open API on a gateway publish must not become ready."""
    provisioner = DockerRuntimeProvisioner(
        tmp_path,
        start_timeout=0.1,
        client=_FakeClient(),
    )
    provisioner._publish_host = (  # pylint: disable=protected-access
        "172.18.0.1"
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
        return _Response()

    monkeypatch.setattr(docker_module, "_open_readiness", urlopen)
    record = replace(_record(tmp_path), host="172.18.0.1", port=8088)

    with pytest.raises(RuntimeError, match="non-loopback"):
        provisioner._wait_until_ready(  # pylint: disable=protected-access
            record,
            "runtime-token",
        )

    assert calls
    assert all(isinstance(call, str) for call in calls)


def test_readiness_accepts_token_boundary_on_gateway_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway publish is allowed once anonymous access is rejected."""
    provisioner = DockerRuntimeProvisioner(
        tmp_path,
        start_timeout=0.1,
        client=_FakeClient(),
    )
    provisioner._publish_host = (  # pylint: disable=protected-access
        "172.18.0.1"
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

    monkeypatch.setattr(docker_module, "_open_readiness", urlopen)
    record = replace(_record(tmp_path), host="172.18.0.1", port=8088)

    result = provisioner._wait_until_ready(  # pylint: disable=protected-access
        record,
        "runtime-token",
    )

    assert result == "token"
    token_request = calls[1]
    assert isinstance(token_request, urllib.request.Request)
    assert token_request.get_header("X-qwenpaw-runtime-token") == (
        "runtime-token"
    )


def test_readiness_accepts_legacy_image_when_publish_is_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loopback publish still accepts a legacy image without a token."""
    provisioner = DockerRuntimeProvisioner(
        tmp_path,
        start_timeout=0.1,
        client=_FakeClient(),
    )
    provisioner._publish_host = "127.0.0.1"  # pylint: disable=protected-access

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

    monkeypatch.setattr(
        docker_module,
        "_open_readiness",
        lambda *_args, **_kwargs: _Response(),
    )
    record = replace(
        _record(tmp_path),
        host="host.docker.internal",
        port=8088,
    )

    result = provisioner._wait_until_ready(  # pylint: disable=protected-access
        record,
        "runtime-token",
    )

    assert result == "loopback_only"


def _closed_tcp_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_open_readiness_ignores_env_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = f"http://127.0.0.1:{_closed_tcp_port()}"
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        monkeypatch.setenv(name, proxy)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"ready"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        url = f"http://127.0.0.1:{port}/api/version"
        # pylint: disable-next=protected-access
        with docker_module._open_readiness(url, timeout=2) as response:
            assert response.status == 200
            assert response.read() == b"ready"
    finally:
        server.shutdown()
        server.server_close()


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


def test_published_port_accepts_only_the_requested_gateway() -> None:
    container = _FakeContainer()
    container.attrs = {
        **container.attrs,
        "NetworkSettings": {
            "Ports": {
                "8088/tcp": [
                    {"HostIp": "172.18.0.1", "HostPort": "32123"},
                ],
            },
        },
    }

    # pylint: disable-next=protected-access
    published = DockerRuntimeProvisioner._published_port(
        container,
        "172.18.0.1",
    )
    assert published == 32123
    with pytest.raises(RuntimeError, match="outside 172.19.0.1"):
        # pylint: disable-next=protected-access
        DockerRuntimeProvisioner._published_port(
            container,
            "172.19.0.1",
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
