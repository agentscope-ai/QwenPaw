# -*- coding: utf-8 -*-
"""Real retiring backend for absolute-worker integration tests."""

import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).parent)]
root = Path(sys.argv[1])
for key in ("WORKING", "SECRET", "BACKUP"):
    os.environ[f"QWENPAW_{key}_DIR"] = str(root / key.lower())

import pytest
from upgrade_suite import (
    isolated_loader,
    distribution,
    channel_source,
    upgrade_manager,
    tree_bytes,
)


async def run():
    monkeypatch = pytest.MonkeyPatch()
    fixture = isolated_loader.__wrapped__(root, monkeypatch)
    loader, _, site, destination = next(fixture)
    try:
        distribution(site, "upgrade-sdk", "1.0")
        source = channel_source(root / "incoming")
        mode = sys.argv[2] if len(sys.argv) > 2 else "restart"
        previous_source = None
        if mode == "crash-after-dependency-rollback":
            previous_source = channel_source(
                destination / "upgrade_fixture",
                requirements="upgrade-sdk>=1,<3\n",
            )
            manifest_file = previous_source / "plugin.json"
            manifest = json.loads(manifest_file.read_text())
            manifest["version"] = "0.9"
            manifest_file.write_text(json.dumps(manifest))
            (previous_source / "old-only.txt").write_text(
                "preserve prior installed source"
            )
            (source / "new-only.txt").write_text("new source must roll back")
        crash_after_commit = mode == "crash-after-commit"
        if mode not in {
            "crash-after-commit",
            "crash-after-first-write",
            "crash-after-dependency-rollback",
        }:
            sys.path.insert(0, str(site))
            import upgrade_sdk

            assert upgrade_sdk.VERSION == "1.0"
        manager = upgrade_manager(loader)
        candidate = await manager.stage(
            source, force=mode == "crash-after-dependency-rollback"
        )
        before = tree_bytes(site)
        report = {
            "candidate": candidate,
            "site": str(site),
            "destination": str(destination),
            "before": before,
            "directory": str(
                root / "host/dependency_upgrades" / candidate["id"]
            ),
            "python": sys.executable,
            "old_source": (
                tree_bytes(previous_source) if previous_source else None
            ),
        }
        (root / "report.json").write_text(json.dumps(report))
        if crash_after_commit:
            from qwenpaw.plugins import dependency_transaction as transaction

            original_save = transaction.atomic_json

            def crash_save(path, value):
                if (
                    Path(path).name == "operation.json"
                    and value.get("status") == "succeeded"
                ):
                    os._exit(97)
                return original_save(path, value)

            monkeypatch.setattr(transaction, "atomic_json", crash_save)
        if mode == "crash-after-first-write":
            from qwenpaw.plugins import dependency_transaction as transaction

            original_write = transaction._write_file

            def crash_write(path, content, file_mode):
                original_write(path, content, file_mode)
                if (
                    Path(path) == site / "upgrade_sdk.py"
                    and content == b"VERSION = '2.0'\n"
                ):
                    os._exit(98)

            monkeypatch.setattr(transaction, "_write_file", crash_write)
        if mode == "crash-after-dependency-rollback":
            from qwenpaw.plugins import dependency_transaction as transaction

            original_rollback = transaction.rollback
            original_load = loader.load_plugin_from_path

            async def fail_after_source(*args, **kwargs):
                await original_load(*args, **kwargs)
                raise RuntimeError(
                    "controlled failure after source publication"
                )

            def crash_after_rollback(directory):
                original_rollback(directory)
                os._exit(99)

            monkeypatch.setattr(
                loader, "load_plugin_from_path", fail_after_source
            )
            monkeypatch.setattr(transaction, "rollback", crash_after_rollback)
        applied = await manager.apply(candidate["id"])
        assert tree_bytes(site) == before
        report["applied"] = applied
        (root / "report.json").write_text(json.dumps(report))
        if mode == "hold-for-worker":
            print("backend-waiting", flush=True)
            sys.stdin.readline()
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        monkeypatch.undo()


asyncio.run(run())
