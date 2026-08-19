# -*- coding: utf-8 -*-
"""Runtime admission policy tests for QwenPaw Hub."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from qwenpaw.hub.config import HubConfig, RuntimeConfig, TenantQuota
from qwenpaw.hub.driver import (
    RuntimeDriver,
    RuntimeDriverAvailability,
    RuntimeDriverUnavailableError,
)
from qwenpaw.hub.models import RuntimeRecord, RuntimeSpec, RuntimeState
from qwenpaw.hub.registry import RuntimeRegistry
from qwenpaw.hub.service import RuntimeService


class _FakeDriver(RuntimeDriver):
    name = "local"
    security_level = "test"

    def __init__(self, available: bool = True) -> None:
        self.available = available

    def preflight(self, root_dir: Path) -> RuntimeDriverAvailability:
        del root_dir
        return RuntimeDriverAvailability(
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
    driver_available: bool = True,
) -> RuntimeService:
    return RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        drivers={"local": _FakeDriver(driver_available)},
        credential_provider=lambda _: {},
        hub_config=config,
    )


def _spec(runtime_id: str, tenant_id: str = "tenant-a") -> RuntimeSpec:
    return RuntimeSpec(
        runtime_id=runtime_id,
        tenant_id=tenant_id,
        owner_user_id=tenant_id,
    )


def test_unavailable_driver_rejects_runtime_registration(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        HubConfig(),
        driver_available=False,
    )

    assert service.runtime_available() is False
    with pytest.raises(
        RuntimeDriverUnavailableError,
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

    assert first.driver == "local"
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


def test_driver_policy_fails_closed_at_startup(tmp_path: Path) -> None:
    config = HubConfig(
        runtime=RuntimeConfig(
            default_driver="docker",
            allowed_drivers=["docker"],
        ),
    )

    with pytest.raises(ValueError, match="Unknown default runtime driver"):
        _service(tmp_path, config)
