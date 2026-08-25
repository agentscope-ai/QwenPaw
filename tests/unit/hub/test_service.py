# -*- coding: utf-8 -*-
"""Runtime admission policy tests for QwenPaw Hub."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from qwenpaw.hub.config import (
    DockerRuntimeConfig,
    HubConfig,
    RuntimeCapacityConfig,
    RuntimeConfig,
)
from qwenpaw.hub.provisioner import (
    RuntimeProvisioner,
    RuntimeProvisionerAvailability,
    RuntimeProvisionerUnavailableError,
)
from qwenpaw.hub.models import (
    RuntimeRecord,
    RuntimeSpec,
    RuntimeStartPolicy,
    RuntimeState,
)
from qwenpaw.hub.registry import RuntimeRegistry
from qwenpaw.hub.service import RuntimeService


class _FakeProvisioner(RuntimeProvisioner):
    name = "local"
    security_level = "test"

    def __init__(
        self,
        available: bool = True,
        *,
        name: str = "local",
        start_error: str | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.start_error = start_error
        self.config: dict[str, object] = {}
        self.status_calls = 0
        self.start_calls = 0
        self.stop_calls = 0

    def configure(self, config: Mapping[str, object]) -> None:
        self.config = dict(config)

    def validate_config(self, value: object) -> dict[str, object]:
        del value
        if self.name != "docker":
            return {}
        return {
            "image": self.config["image"],
            "pull_policy": self.config["pull_policy"],
        }

    def preflight(self, root_dir: Path) -> RuntimeProvisionerAvailability:
        del root_dir
        return RuntimeProvisionerAvailability(
            available=self.available,
            reason=None if self.available else "sandbox unavailable",
        )

    def start(
        self,
        record: RuntimeRecord,
        credentials: Mapping[str, str],
    ) -> RuntimeRecord:
        del credentials
        self.start_calls += 1
        if self.start_error is not None:
            raise RuntimeError(self.start_error)
        return replace(record, state=RuntimeState.RUNNING, pid=100)

    def stop(self, record: RuntimeRecord) -> RuntimeRecord:
        self.stop_calls += 1
        return replace(record, state=RuntimeState.STOPPED, pid=None)

    def status(self, record: RuntimeRecord) -> RuntimeRecord:
        self.status_calls += 1
        return record

    def close(self) -> None:
        return None


def _service(
    tmp_path: Path,
    config: HubConfig,
    *,
    provisioner_available: bool = True,
) -> RuntimeService:
    return RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        provisioners={"local": _FakeProvisioner(provisioner_available)},
        credential_provider=lambda _: {},
        hub_config=config,
    )


def _spec(runtime_id: str, tenant_id: str = "tenant-a") -> RuntimeSpec:
    return RuntimeSpec(
        runtime_id=runtime_id,
        tenant_id=tenant_id,
        owner_user_id=tenant_id,
    )


def _docker_config(image: str) -> HubConfig:
    return HubConfig(
        runtime=RuntimeConfig(
            provisioner="docker",
            docker=DockerRuntimeConfig(
                source="custom",
                image=image,
                pull_policy="never",
            ),
        ),
    )


def _backend_service(
    tmp_path: Path,
    *,
    config: HubConfig | None = None,
    docker_start_error: str | None = None,
) -> tuple[RuntimeService, _FakeProvisioner, _FakeProvisioner]:
    local = _FakeProvisioner(name="local")
    docker = _FakeProvisioner(
        name="docker",
        start_error=docker_start_error,
    )
    service = RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        provisioners={"local": local, "docker": docker},
        credential_provider=lambda _: {},
        hub_config=config or HubConfig(),
    )
    return service, local, docker


def test_unavailable_provisioner_rejects_runtime_registration(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        HubConfig(),
        provisioner_available=False,
    )

    assert service.runtime_available() is False
    with pytest.raises(
        RuntimeProvisionerUnavailableError,
        match="sandbox unavailable",
    ):
        service.create(_spec("blocked"))
    assert service.registry.list() == []


def test_one_runtime_is_allowed_per_tenant(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    first = service.create(_spec("first"))

    assert first.provisioner == "local"
    with pytest.raises(ValueError, match="already has a runtime"):
        service.create(_spec("second"))
    assert service.create(_spec("other", "tenant-b")).tenant_id == "tenant-b"


def test_runtime_cannot_override_administrator_backend(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    spec = replace(_spec("runtime-a"), provisioner="docker")

    with pytest.raises(ValueError, match="controlled by the administrator"):
        service.create(spec)

    assert service.registry.list() == []


@pytest.mark.parametrize(
    "runtime_id",
    ["Runtime-A", "runtime-a.", "con", "nul.txt", "com1", "lpt9.log"],
)
def test_runtime_id_rejects_cross_platform_directory_collisions(
    tmp_path: Path,
    runtime_id: str,
) -> None:
    service = _service(tmp_path, HubConfig())

    with pytest.raises(ValueError, match="Invalid runtime_id"):
        service.create(_spec(runtime_id))

    assert service.registry.list() == []


def test_managed_runtime_rejects_non_loopback_host(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    created = service.create(_spec("runtime-a"))
    service.registry.save(
        replace(created, host="192.0.2.10"),
    )

    with pytest.raises(ValueError, match="loopback-only"):
        service.start(created.runtime_id)

    assert service.get(created.runtime_id).state is RuntimeState.CREATED


def test_running_runtime_limit_is_global(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        HubConfig(
            capacity=RuntimeCapacityConfig(
                max_running_runtimes=1,
            ),
        ),
    )
    service.create(_spec("first"))
    service.create(_spec("second", "tenant-b"))

    assert service.start("first").state is RuntimeState.RUNNING
    with pytest.raises(ValueError, match="running runtime limit reached: 1"):
        service.start("second")


@pytest.mark.parametrize(
    "initial_state, expected_start_calls, expected_stop_calls",
    [
        (RuntimeState.RUNNING, 2, 1),
        (RuntimeState.FAILED, 1, 0),
    ],
)
def test_restart_applies_state_transition(
    tmp_path: Path,
    initial_state: RuntimeState,
    expected_start_calls: int,
    expected_stop_calls: int,
) -> None:
    service = _service(tmp_path, HubConfig())
    created = service.create(_spec("runtime-a"))
    if initial_state is RuntimeState.RUNNING:
        service.start("runtime-a")
    else:
        service.registry.save(
            replace(created, state=initial_state, last_error="crashed"),
        )

    restarted = service.restart("runtime-a")

    provisioner = service.provisioners["local"]
    assert isinstance(provisioner, _FakeProvisioner)
    assert restarted.state is RuntimeState.RUNNING
    assert provisioner.start_calls == expected_start_calls
    assert provisioner.stop_calls == expected_stop_calls


@pytest.mark.parametrize(
    (
        "initial_image",
        "target_image",
        "start_error",
        "expected_docker_starts",
    ),
    [
        (None, "qwenpaw-hub-test:pr-7112", None, 1),
        ("qwenpaw:test-old", "qwenpaw:test-new", None, 2),
        (None, "qwenpaw:test", "container failed", 1),
    ],
    ids=["backend-switch", "image-refresh", "target-failure"],
)
def test_restart_applies_current_backend_policy(
    tmp_path: Path,
    initial_image: str | None,
    target_image: str,
    start_error: str | None,
    expected_docker_starts: int,
) -> None:
    initial_config = (
        _docker_config(initial_image) if initial_image else HubConfig()
    )
    service, local, docker = _backend_service(
        tmp_path,
        config=initial_config,
        docker_start_error=start_error,
    )
    service.create(_spec("runtime-a"))
    service.start("runtime-a")
    service.apply_config(_docker_config(target_image))

    if start_error:
        with pytest.raises(RuntimeError, match=start_error):
            service.restart("runtime-a")
        restarted = service.get("runtime-a")
        assert restarted.last_error == start_error
    else:
        restarted = service.restart("runtime-a")

    assert restarted.provisioner == "docker"
    assert restarted.state is (
        RuntimeState.FAILED if start_error else RuntimeState.RUNNING
    )
    assert restarted.host == "127.0.0.1"
    assert restarted.port == 0
    assert restarted.metadata["docker"] == {
        "image": target_image,
        "pull_policy": "never",
    }
    source = docker if initial_image else local
    assert source.stop_calls == 1
    assert docker.start_calls == expected_docker_starts


def test_owner_can_restart_runtime_after_recoverable_stop(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, HubConfig())
    service.create(_spec("runtime-a"))
    service.start("runtime-a")

    stopped = service.stop("runtime-a")
    restarted = service.restart("runtime-a", owner_initiated=True)

    assert stopped.desired_state is RuntimeState.STOPPED
    assert stopped.start_policy is RuntimeStartPolicy.OWNER_ALLOWED
    assert restarted.state is RuntimeState.RUNNING
    assert restarted.desired_state is RuntimeState.RUNNING


def test_owner_cannot_restart_admin_disabled_runtime(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    service.create(_spec("runtime-a"))
    service.start("runtime-a")
    disabled = service.stop(
        "runtime-a",
        start_policy=RuntimeStartPolicy.ADMIN_ONLY,
    )

    with pytest.raises(PermissionError, match="administrator"):
        service.restart("runtime-a", owner_initiated=True)

    persisted = service.get("runtime-a")
    assert disabled.start_policy is RuntimeStartPolicy.ADMIN_ONLY
    assert persisted.desired_state is RuntimeState.STOPPED
    assert persisted.state is RuntimeState.STOPPED


def test_close_preserves_runtime_control_intent(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    service.create(_spec("running"))
    service.create(_spec("disabled", "tenant-b"))
    service.start("running")
    service.stop(
        "disabled",
        start_policy=RuntimeStartPolicy.ADMIN_ONLY,
    )

    service.close()

    running = service.get("running")
    disabled = service.get("disabled")
    assert running.state is RuntimeState.STOPPED
    assert running.desired_state is RuntimeState.RUNNING
    assert disabled.desired_state is RuntimeState.STOPPED
    assert disabled.start_policy is RuntimeStartPolicy.ADMIN_ONLY


def test_provisioner_policy_fails_closed_at_startup(tmp_path: Path) -> None:
    config = HubConfig(
        runtime=RuntimeConfig(
            provisioner="docker",
        ),
    )

    with pytest.raises(
        ValueError,
        match="Unknown runtime provisioner",
    ):
        _service(tmp_path, config)


def test_runtime_page_refreshes_only_returned_records(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    for index in range(5):
        service.create(_spec(f"runtime-{index}", f"tenant-{index}"))

    records, total = service.list_page(
        page=2,
        page_size=2,
        query="runtime",
        state=RuntimeState.CREATED,
    )

    assert total == 5
    assert len(records) == 2
    provisioner = service.provisioners["local"]
    assert isinstance(provisioner, _FakeProvisioner)
    assert provisioner.status_calls == 2
