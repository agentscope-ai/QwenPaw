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


def test_restart_replaces_running_runtime(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    service.create(_spec("runtime-a"))
    service.start("runtime-a")

    restarted = service.restart("runtime-a")

    provisioner = service.provisioners["local"]
    assert isinstance(provisioner, _FakeProvisioner)
    assert restarted.state is RuntimeState.RUNNING
    assert provisioner.start_calls == 2
    assert provisioner.stop_calls == 1


def test_restart_starts_failed_runtime_without_stopping(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, HubConfig())
    created = service.create(_spec("runtime-a"))
    service.registry.save(
        replace(created, state=RuntimeState.FAILED, last_error="crashed"),
    )

    restarted = service.restart("runtime-a")

    provisioner = service.provisioners["local"]
    assert isinstance(provisioner, _FakeProvisioner)
    assert restarted.state is RuntimeState.RUNNING
    assert provisioner.start_calls == 1
    assert provisioner.stop_calls == 0


def test_restart_switches_to_current_administrator_backend(
    tmp_path: Path,
) -> None:
    local = _FakeProvisioner(name="local")
    docker = _FakeProvisioner(name="docker")
    service = RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        provisioners={"local": local, "docker": docker},
        credential_provider=lambda _: {},
        hub_config=HubConfig(),
    )
    service.create(_spec("runtime-a"))
    service.start("runtime-a")
    service.apply_config(
        HubConfig(
            runtime=RuntimeConfig(
                provisioner="docker",
                docker=DockerRuntimeConfig(
                    source="custom",
                    image="qwenpaw-hub-test:pr-7112",
                    pull_policy="never",
                ),
            ),
        ),
    )

    restarted = service.restart("runtime-a", owner_initiated=True)

    assert restarted.provisioner == "docker"
    assert restarted.host == "127.0.0.1"
    assert restarted.port == 0
    assert restarted.metadata["docker"] == {
        "image": "qwenpaw-hub-test:pr-7112",
        "pull_policy": "never",
    }
    assert local.stop_calls == 1
    assert docker.start_calls == 1


def test_restart_refreshes_current_docker_image_policy(
    tmp_path: Path,
) -> None:
    local = _FakeProvisioner(name="local")
    docker = _FakeProvisioner(name="docker")
    initial_config = HubConfig(
        runtime=RuntimeConfig(
            provisioner="docker",
            docker=DockerRuntimeConfig(
                source="custom",
                image="qwenpaw:test-old",
                pull_policy="never",
            ),
        ),
    )
    service = RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        provisioners={"local": local, "docker": docker},
        credential_provider=lambda _: {},
        hub_config=initial_config,
    )
    service.create(_spec("runtime-a"))
    service.start("runtime-a")
    service.apply_config(
        initial_config.model_copy(
            update={
                "runtime": RuntimeConfig(
                    provisioner="docker",
                    docker=DockerRuntimeConfig(
                        source="custom",
                        image="qwenpaw:test-new",
                        pull_policy="never",
                    ),
                ),
            },
        ),
    )

    restarted = service.restart("runtime-a")

    assert restarted.metadata["docker"] == {
        "image": "qwenpaw:test-new",
        "pull_policy": "never",
    }
    assert docker.stop_calls == 1
    assert docker.start_calls == 2


def test_restart_persists_target_backend_failure(tmp_path: Path) -> None:
    local = _FakeProvisioner(name="local")
    docker = _FakeProvisioner(
        name="docker",
        start_error="container failed",
    )
    service = RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        provisioners={"local": local, "docker": docker},
        credential_provider=lambda _: {},
        hub_config=HubConfig(),
    )
    service.create(_spec("runtime-a"))
    service.start("runtime-a")
    service.apply_config(
        HubConfig(
            runtime=RuntimeConfig(
                provisioner="docker",
                docker=DockerRuntimeConfig(
                    source="custom",
                    image="qwenpaw:test",
                    pull_policy="never",
                ),
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="container failed"):
        service.restart("runtime-a")

    failed = service.get("runtime-a")
    assert failed.provisioner == "docker"
    assert failed.state is RuntimeState.FAILED
    assert failed.last_error == "container failed"
    assert local.stop_calls == 1


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
