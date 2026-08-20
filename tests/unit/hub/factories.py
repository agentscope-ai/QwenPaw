# -*- coding: utf-8 -*-
"""Shared factories for QwenPaw Hub unit tests."""

from pathlib import Path

from qwenpaw.hub.models import RuntimeRecord, RuntimeState


def runtime_record(
    tmp_path: Path,
    metadata: dict | None = None,
    *,
    runtime_id: str = "runtime-a",
    tenant_id: str = "tenant-a",
    owner_user_id: str = "user-a",
    provisioner: str = "local",
    port: int = 9001,
    state: RuntimeState = RuntimeState.CREATED,
) -> RuntimeRecord:
    """Build a runtime record with an isolated temporary directory tree."""
    root = tmp_path / "runtimes" / runtime_id
    for name in ("working", "secrets", "backups", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return RuntimeRecord(
        runtime_id=runtime_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        provisioner=provisioner,
        host="127.0.0.1",
        port=port,
        state=state,
        working_dir=root / "working",
        secret_dir=root / "secrets",
        backup_dir=root / "backups",
        log_file=root / "logs" / "app.log",
        metadata=metadata or {},
    )
