# -*- coding: utf-8 -*-
"""Runtime admission policy tests for QwenPaw Hub."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from qwenpaw.hub.config import HubConfig, RuntimeConfig, TenantQuota
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

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.status_calls = 0
        self.start_calls = 0
        self.stop_calls = 0

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


def test_runtime_total_limit_is_tenant_scoped(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        HubConfig(tenant_defaults=TenantQuota(max_runtimes=1)),
    )
    first = service.create(_spec("first"))

    assert first.provisioner == "local"
    with pytest.raises(ValueError, match="runtime limit reached: 1"):
        service.create(_spec("second"))
    assert service.create(_spec("other", "tenant-b")).tenant_id == "tenant-b"


def test_runtime_cannot_override_administrator_backend(tmp_path: Path) -> None:
    service = _service(tmp_path, HubConfig())
    spec = replace(_spec("runtime-a"), provisioner="docker")

    with pytest.raises(ValueError, match="controlled by the administrator"):
        service.create(spec)

    assert service.registry.list() == []


def test_running_runtime_limit_is_tenant_scoped(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        HubConfig(
            tenant_defaults=TenantQuota(
                max_runtimes=2,
                max_running_runtimes=1,
            ),
        ),
    )
    service.create(_spec("first"))
    service.create(_spec("second"))

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
    service.create(_spec("disabled"))
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
        service.create(_spec(f"runtime-{index}"))

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
