# -*- coding: utf-8 -*-
"""Runtime admission policy tests for QwenPaw Pro."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from qwenpaw.pro.config import ProConfig, RuntimeConfig, TenantQuota
from qwenpaw.pro.driver import RuntimeDriver
from qwenpaw.pro.models import RuntimeRecord, RuntimeSpec, RuntimeState
from qwenpaw.pro.registry import RuntimeRegistry
from qwenpaw.pro.service import RuntimeService


class _FakeDriver(RuntimeDriver):
    name = "local"
    security_level = "test"

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


def _service(tmp_path: Path, config: ProConfig) -> RuntimeService:
    return RuntimeService(
        root_dir=tmp_path,
        registry=RuntimeRegistry(tmp_path / "control.db"),
        drivers={"local": _FakeDriver()},
        credential_provider=lambda _: {},
        pro_config=config,
    )


def _spec(runtime_id: str, tenant_id: str = "tenant-a") -> RuntimeSpec:
    return RuntimeSpec(
        runtime_id=runtime_id,
        tenant_id=tenant_id,
        owner_user_id=tenant_id,
    )


def test_runtime_total_limit_is_tenant_scoped(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        ProConfig(tenant_defaults=TenantQuota(max_runtimes=1)),
    )
    first = service.create(_spec("first"))

    assert first.driver == "local"
    with pytest.raises(ValueError, match="runtime limit reached: 1"):
        service.create(_spec("second"))
    assert service.create(_spec("other", "tenant-b")).tenant_id == "tenant-b"


def test_running_runtime_limit_is_tenant_scoped(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        ProConfig(
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
    config = ProConfig(
        runtime=RuntimeConfig(
            default_driver="docker",
            allowed_drivers=["docker"],
        ),
    )

    with pytest.raises(ValueError, match="Unknown default runtime driver"):
        _service(tmp_path, config)
