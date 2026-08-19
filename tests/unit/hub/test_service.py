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
from qwenpaw.hub.models import RuntimeRecord, RuntimeSpec, RuntimeState
from qwenpaw.hub.registry import RuntimeRegistry
from qwenpaw.hub.service import RuntimeService


class _FakeProvisioner(RuntimeProvisioner):
    name = "local"
    security_level = "test"

    def __init__(self, available: bool = True) -> None:
        self.available = available

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
        return replace(record, state=RuntimeState.RUNNING, pid=100)

    def stop(self, record: RuntimeRecord) -> RuntimeRecord:
        return replace(record, state=RuntimeState.STOPPED, pid=None)

    def status(self, record: RuntimeRecord) -> RuntimeRecord:
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


def test_provisioner_policy_fails_closed_at_startup(tmp_path: Path) -> None:
    config = HubConfig(
        runtime=RuntimeConfig(
            default_provisioner="docker",
            allowed_provisioners=["docker"],
        ),
    )

    with pytest.raises(
        ValueError,
        match="Unknown default runtime provisioner",
    ):
        _service(tmp_path, config)
