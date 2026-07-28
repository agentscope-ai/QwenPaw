# -*- coding: utf-8 -*-
import json
from importlib.metadata import PackageNotFoundError
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from packaging.requirements import Requirement
import pytest

from qwenpaw.package_runtime import (
    RuntimeTransaction,
    build_runtime_snapshot,
    environment_requirement_satisfied,
    recover_runtime_if_needed,
    recover_runtime_transactions,
    runtime_requirement_state,
    runtime_write_lock,
    verify_runtime_requirements,
)


@pytest.mark.parametrize(
    ("distribution", "import_name"),
    [
        ("audioop-lts", "audioop"),
        ("discord-py", "discord"),
        ("livekit-api", "livekit"),
        ("matrix-nio", "nio"),
        ("paho-mqtt", "paho"),
        ("pycryptodome", "Crypto"),
        ("pyVoIP", "pyVoIP"),
        ("websocket-client", "websocket"),
        ("wecom-aibot-python-sdk", "aibot"),
        ("demo-package", "demo_package"),
    ],
)
def test_environment_requirement_uses_import_name(distribution, import_name):
    with (
        patch(
            "qwenpaw.package_runtime.distribution_version",
            side_effect=PackageNotFoundError,
        ),
        patch(
            "qwenpaw.package_runtime.importlib.util.find_spec",
            return_value=object(),
        ) as find_spec,
    ):
        assert environment_requirement_satisfied(
            Requirement(distribution),
        )

    find_spec.assert_called_once_with(import_name)


def _write_metadata(
    site_dir: Path,
    directory: str,
    *,
    name: str | None,
    version: str | None,
) -> None:
    metadata_dir = site_dir / directory
    metadata_dir.mkdir(parents=True)
    lines = []
    if name is not None:
        lines.append(f"Name: {name}")
    if version is not None:
        lines.append(f"Version: {version}")
    content = "\n".join(lines)
    (metadata_dir / "METADATA").write_text(
        f"{content}\n",
        encoding="utf-8",
    )


def _write_distribution(
    site_dir: Path,
    *,
    name: str,
    version: str,
    files: dict[str, str],
    requirements: tuple[str, ...] = (),
) -> None:
    metadata_name = name.replace("-", "_")
    metadata_dir = site_dir / f"{metadata_name}-{version}.dist-info"
    metadata_dir.mkdir(parents=True)
    requirement_lines = "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requirements
    )
    (metadata_dir / "METADATA").write_text(
        f"Name: {name}\nVersion: {version}\n{requirement_lines}",
        encoding="utf-8",
    )
    record_paths = []
    for relative, content in files.items():
        path = site_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        record_paths.append(relative)
    metadata_relative = metadata_dir.relative_to(site_dir)
    record_paths.extend(
        [
            str(metadata_relative / "METADATA"),
            str(metadata_relative / "RECORD"),
        ],
    )
    (metadata_dir / "RECORD").write_text(
        "".join(f"{path},,\n" for path in record_paths),
        encoding="utf-8",
    )


def test_snapshot_canonicalizes_distribution_names(tmp_path):
    _write_metadata(
        tmp_path,
        "discord_py-2.7.1.dist-info",
        name="discord.py",
        version="2.7.1",
    )

    snapshot = build_runtime_snapshot(tmp_path)

    assert snapshot.entries("discord-py") == snapshot.entries("discord_py")
    assert snapshot.entries("discord.py")[0].version == "2.7.1"


def test_snapshot_reports_duplicate_metadata_as_conflict(tmp_path):
    _write_metadata(
        tmp_path,
        "discord_py-2.3.2.dist-info",
        name="discord-py",
        version="2.3.2",
    )
    _write_metadata(
        tmp_path,
        "discord_py-2.7.1.dist-info",
        name="discord.py",
        version="2.7.1",
    )

    state = runtime_requirement_state(
        Requirement("discord-py==2.7.1"),
        build_runtime_snapshot(tmp_path),
    )

    assert state == "runtime_conflict"


def test_transaction_rejects_duplicate_staging_metadata(tmp_path):
    site_dir = tmp_path / "site"
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="1.0",
        files={"demo.py": "one\n"},
    )
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "two\n"},
    )

    with pytest.raises(RuntimeError, match="invalid metadata"):
        transaction.commit()


def test_transaction_rejects_consumer_version_conflict(tmp_path):
    site_dir = tmp_path / "site"
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="shared-package",
        version="2.0",
        files={"shared.py": "two\n"},
    )

    with pytest.raises(RuntimeError, match="dependency conflict"):
        transaction.commit(constraints=["shared-package<2"])

    assert not site_dir.exists()


def test_transaction_checks_installed_distribution_constraints(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="consumer-package",
        version="1.0",
        files={"consumer.py": "consumer\n"},
        requirements=("shared-package<2",),
    )
    _write_distribution(
        site_dir,
        name="shared-package",
        version="1.0",
        files={"shared.py": "one\n"},
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="shared-package",
        version="2.0",
        files={"shared.py": "two\n"},
    )

    with pytest.raises(RuntimeError, match="dependency conflict"):
        transaction.commit()

    assert (site_dir / "shared.py").read_text() == "one\n"


def test_unrelated_invalid_requires_dist_does_not_block_update(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="consumer-package",
        version="1.0",
        files={"consumer.py": "consumer\n"},
        requirements=("not a valid requirement !!!",),
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="shared-package",
        version="2.0",
        files={"shared.py": "two\n"},
    )

    transaction.commit()

    assert (site_dir / "shared.py").read_text() == "two\n"


def test_snapshot_reports_damaged_target_metadata_as_conflict(tmp_path):
    _write_metadata(
        tmp_path,
        "discord_py-2.7.1.dist-info",
        name=None,
        version=None,
    )

    state = runtime_requirement_state(
        Requirement("discord-py==2.7.1"),
        build_runtime_snapshot(tmp_path),
    )

    assert state == "runtime_conflict"


def test_snapshot_reports_invalid_version_as_conflict(tmp_path):
    _write_metadata(
        tmp_path,
        "demo-unknown.dist-info",
        name="demo",
        version="definitely-not-a-version!!!",
    )

    state = runtime_requirement_state(
        Requirement("demo==1.0"),
        build_runtime_snapshot(tmp_path),
    )

    assert state == "runtime_conflict"


def test_unrelated_damaged_metadata_does_not_affect_requirement(tmp_path):
    _write_metadata(
        tmp_path,
        "broken_package-1.0.dist-info",
        name=None,
        version=None,
    )
    _write_metadata(
        tmp_path,
        "discord_py-2.7.1.dist-info",
        name="discord-py",
        version="2.7.1",
    )

    state = runtime_requirement_state(
        Requirement("discord-py==2.7.1"),
        build_runtime_snapshot(tmp_path),
    )

    assert state == "satisfied"


def test_snapshot_uses_fallback_only_when_runtime_has_no_target(tmp_path):
    snapshot = build_runtime_snapshot(tmp_path)

    state = runtime_requirement_state(
        Requirement("bundled-package==1.0"),
        snapshot,
        fallback=lambda requirement: requirement.name == "bundled-package",
    )

    assert state == "satisfied"


def test_snapshot_passes_versioned_requirement_to_fallback(tmp_path):
    requirement = Requirement("bundled-package==2.0")
    received = []

    def fallback(value):
        received.append(value)
        return False

    state = runtime_requirement_state(
        requirement,
        build_runtime_snapshot(tmp_path),
        fallback=fallback,
    )

    assert state == "missing"
    assert received == [requirement]


def test_transaction_replaces_duplicate_metadata_and_old_files(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={
            "demo/__init__.py": "version = 'old'\n",
            "demo/removed.py": "old = True\n",
        },
    )
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.1",
        files={"demo/__init__.py": "version = 'stale'\n"},
    )
    incomplete_record = site_dir / "demo_package-1.1.dist-info" / "RECORD"
    incomplete_record.write_text(
        "demo/__init__.py,,\n",
        encoding="utf-8",
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo/__init__.py": "version = 'new'\n"},
    )

    transaction.commit()

    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["2.0"]
    assert (site_dir / "demo/__init__.py").read_text() == "version = 'new'\n"
    assert not (site_dir / "demo/removed.py").exists()


def test_transaction_removes_metadata_omitted_from_record(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo.py": "old\n"},
    )
    old_metadata = site_dir / "demo_package-1.0.dist-info"
    (old_metadata / "RECORD").write_text(
        "demo.py,,\ndemo_package-1.0.dist-info/METADATA,,\n",
        encoding="utf-8",
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "new\n"},
    )

    transaction.commit()

    assert not old_metadata.exists()
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["2.0"]


def test_transaction_removes_replaced_egg_info_file(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    egg_info = site_dir / "demo_package.egg-info"
    egg_info.write_text(
        "Name: demo-package\nVersion: 1.0\n",
        encoding="utf-8",
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "new\n"},
    )

    transaction.commit()

    assert not egg_info.exists()
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["2.0"]


def test_transaction_leaves_unrelated_duplicate_metadata_untouched(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="other-package",
        version="1.0",
        files={"other.py": "one\n"},
    )
    _write_distribution(
        site_dir,
        name="other-package",
        version="2.0",
        files={"other.py": "two\n"},
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="1.0",
        files={"demo.py": "demo\n"},
    )

    transaction.commit()

    entries = build_runtime_snapshot(site_dir).entries("other-package")
    assert {entry.version for entry in entries} == {"1.0", "2.0"}


def test_transaction_preserves_identical_shared_file(tmp_path):
    site_dir = tmp_path / "site"
    shared = {"shared_namespace/common.py": "shared\n"}
    _write_distribution(
        site_dir,
        name="first-package",
        version="1.0",
        files=shared,
    )
    _write_distribution(
        site_dir,
        name="second-package",
        version="1.0",
        files=shared,
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="first-package",
        version="2.0",
        files=shared,
    )

    transaction.commit()

    assert (site_dir / "shared_namespace/common.py").read_text() == "shared\n"
    assert build_runtime_snapshot(site_dir).entries("second-package")


def test_transaction_preserves_shared_file_removed_by_new_version(tmp_path):
    site_dir = tmp_path / "site"
    shared = {"shared_namespace/common.py": "shared\n"}
    _write_distribution(
        site_dir,
        name="first-package",
        version="1.0",
        files=shared,
    )
    _write_distribution(
        site_dir,
        name="second-package",
        version="1.0",
        files=shared,
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="first-package",
        version="2.0",
        files={"first.py": "new\n"},
    )

    transaction.commit()

    assert (site_dir / "shared_namespace/common.py").read_text() == "shared\n"
    assert build_runtime_snapshot(site_dir).entries("second-package")


def test_transaction_rejects_changed_shared_file(tmp_path):
    site_dir = tmp_path / "site"
    shared = {"shared_namespace/common.py": "shared\n"}
    _write_distribution(
        site_dir,
        name="first-package",
        version="1.0",
        files=shared,
    )
    _write_distribution(
        site_dir,
        name="second-package",
        version="1.0",
        files=shared,
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="first-package",
        version="2.0",
        files={"shared_namespace/common.py": "changed\n"},
    )

    with pytest.raises(RuntimeError, match="Runtime file conflict"):
        transaction.commit()

    assert (site_dir / "shared_namespace/common.py").read_text() == "shared\n"


def test_transaction_allows_identical_unmanaged_file(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "demo.py").write_text("same\n", encoding="utf-8")
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="1.0",
        files={"demo.py": "same\n"},
    )

    transaction.commit()

    assert (site_dir / "demo.py").read_text() == "same\n"


def test_transaction_rejects_changed_unmanaged_file(tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "demo.py").write_text("old\n", encoding="utf-8")
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="1.0",
        files={"demo.py": "new\n"},
    )

    with pytest.raises(RuntimeError, match="unmanaged file conflict"):
        transaction.commit()

    assert (site_dir / "demo.py").read_text() == "old\n"


def test_transaction_rejects_record_path_outside_runtime(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo.py": "old\n"},
    )
    metadata = site_dir / "demo_package-1.0.dist-info" / "RECORD"
    metadata.write_text("../outside.py,,\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("keep\n", encoding="utf-8")
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "new\n"},
    )

    with pytest.raises(RuntimeError, match="escapes root"):
        transaction.commit()

    assert outside.read_text() == "keep\n"


@pytest.mark.parametrize("script_dir", ["bin", "Scripts"])
def test_transaction_accepts_target_script_record_paths(tmp_path, script_dir):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    _write_distribution(
        site_dir,
        name="script-package",
        version="1.0",
        files={f"{script_dir}/script-tool": "#!/usr/bin/env python\n"},
    )
    metadata = site_dir / "script_package-1.0.dist-info" / "RECORD"
    metadata.write_text(
        f"../../{script_dir}/script-tool,,\n"
        "script_package-1.0.dist-info/METADATA,,\n"
        "script_package-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="second-package",
        version="1.0",
        files={"second.py": "value\n"},
    )

    transaction.commit()

    assert (site_dir / script_dir / "script-tool").is_file()
    assert (site_dir / "second.py").read_text() == "value\n"


def test_transaction_rolls_back_when_verification_fails(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo.py": "old\n"},
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "new\n"},
    )

    with pytest.raises(RuntimeError, match="verify failed"):
        transaction.commit(
            verify=lambda: (_ for _ in ()).throw(
                RuntimeError("verify failed"),
            ),
        )

    assert (site_dir / "demo.py").read_text() == "old\n"
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["1.0"]


def test_transaction_moves_exclusive_directory_without_copying_files(
    tmp_path,
):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={
            "demo/__init__.py": "old\n",
            "demo/generated/item.py": "old item\n",
        },
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={
            "demo/__init__.py": "new\n",
            "demo/generated/item.py": "new item\n",
        },
    )
    original_copy = shutil.copy2

    def reject_directory_file_copy(source, destination, *args, **kwargs):
        source_path = Path(source)
        if "demo" in source_path.parts:
            raise AssertionError("exclusive directory files were copied")
        return original_copy(source, destination, *args, **kwargs)

    with patch(
        "qwenpaw.package_runtime.shutil.copy2",
        side_effect=reject_directory_file_copy,
    ):
        transaction.commit()

    assert (site_dir / "demo/__init__.py").read_text() == "new\n"
    assert (site_dir / "demo/generated/item.py").read_text() == ("new item\n")


def test_transaction_moves_directory_into_missing_site(tmp_path):
    site_dir = tmp_path / "site"
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="1.0",
        files={"demo/__init__.py": "new\n"},
    )

    transaction.commit()

    assert (site_dir / "demo/__init__.py").read_text() == "new\n"
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["1.0"]


def test_transaction_restores_exclusive_directory_after_verify_failure(
    tmp_path,
):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo/__init__.py": "old\n"},
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo/__init__.py": "new\n"},
    )

    with pytest.raises(RuntimeError, match="verify failed"):
        transaction.commit(
            verify=lambda: (_ for _ in ()).throw(
                RuntimeError("verify failed"),
            ),
        )

    assert (site_dir / "demo/__init__.py").read_text() == "old\n"
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["1.0"]


def test_transaction_does_not_move_directory_with_unmanaged_file(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo/__init__.py": "old\n"},
    )
    unmanaged = site_dir / "demo/local.py"
    unmanaged.write_text("keep\n", encoding="utf-8")
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo/__init__.py": "new\n"},
    )

    transaction.commit()

    assert (site_dir / "demo/__init__.py").read_text() == "new\n"
    assert unmanaged.read_text() == "keep\n"


def test_transaction_rolls_back_when_runtime_file_is_locked(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo.py": "old\n"},
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "new\n"},
    )
    original_copy = shutil.copy2

    def copy_with_locked_runtime(source, destination, *args, **kwargs):
        source_path = Path(source)
        if (
            transaction.staging_dir in source_path.parents
            and source_path.name == "demo.py"
        ):
            raise PermissionError("file is in use")
        return original_copy(source, destination, *args, **kwargs)

    with (
        patch(
            "qwenpaw.package_runtime.shutil.copy2",
            side_effect=copy_with_locked_runtime,
        ),
        pytest.raises(PermissionError, match="file is in use"),
    ):
        transaction.commit()

    assert (site_dir / "demo.py").read_text() == "old\n"
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["1.0"]


def test_transaction_does_not_rollback_incomplete_backup(tmp_path):
    site_dir = tmp_path / "site"
    _write_distribution(
        site_dir,
        name="demo-package",
        version="1.0",
        files={"demo.py": "old\n"},
    )
    transaction = RuntimeTransaction(site_dir)
    staging = transaction.create()
    _write_distribution(
        staging,
        name="demo-package",
        version="2.0",
        files={"demo.py": "new\n"},
    )

    with (
        patch(
            "qwenpaw.package_runtime.shutil.copy2",
            side_effect=PermissionError("backup failed"),
        ),
        pytest.raises(PermissionError, match="backup failed"),
    ):
        transaction.commit()

    assert (site_dir / "demo.py").read_text() == "old\n"
    entries = build_runtime_snapshot(site_dir).entries("demo-package")
    assert [entry.version for entry in entries] == ["1.0"]
    assert not transaction.transaction_dir.exists()


def test_recover_runtime_transactions_restores_committing_backup(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    site_dir.mkdir(parents=True)
    (site_dir / "demo.py").write_text("new\n", encoding="utf-8")
    transaction_dir = site_dir.parent / ".transactions" / "interrupted"
    backup = transaction_dir / "backup"
    backup.mkdir(parents=True)
    (backup / "demo.py").write_text("old\n", encoding="utf-8")
    (transaction_dir / "manifest.json").write_text(
        """{
  "state": "committing",
  "backup_paths": ["demo.py"],
  "staged_paths": ["demo.py"]
}
""",
        encoding="utf-8",
    )

    recover_runtime_transactions(site_dir)

    assert (site_dir / "demo.py").read_text() == "old\n"
    assert not transaction_dir.exists()


def test_recover_runtime_transactions_restores_directory_backup(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    current = site_dir / "demo"
    current.mkdir(parents=True)
    (current / "__init__.py").write_text("new\n", encoding="utf-8")
    transaction_dir = site_dir.parent / ".transactions" / "interrupted"
    backup = transaction_dir / "backup" / "demo"
    backup.mkdir(parents=True)
    (backup / "__init__.py").write_text("old\n", encoding="utf-8")
    (transaction_dir / "manifest.json").write_text(
        """{
  "state": "committing",
  "backup_paths": [],
  "staged_paths": [],
  "directory_paths": ["demo"],
  "directory_backup_paths": ["demo"]
}
""",
        encoding="utf-8",
    )

    recover_runtime_transactions(site_dir)

    assert (site_dir / "demo/__init__.py").read_text() == "old\n"
    assert not transaction_dir.exists()


def test_recovery_copy_failure_keeps_current_runtime_file(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    site_dir.mkdir(parents=True)
    current = site_dir / "demo.py"
    current.write_text("new\n", encoding="utf-8")
    transaction_dir = site_dir.parent / ".transactions" / "interrupted"
    backup = transaction_dir / "backup"
    backup.mkdir(parents=True)
    (backup / "demo.py").write_text("old\n", encoding="utf-8")
    (transaction_dir / "manifest.json").write_text(
        """{
  "state": "committing",
  "backup_paths": ["demo.py"],
  "staged_paths": ["demo.py"]
}
""",
        encoding="utf-8",
    )

    with (
        patch(
            "qwenpaw.package_runtime.shutil.copy2",
            side_effect=PermissionError("restore copy failed"),
        ),
        pytest.raises(RuntimeError, match="Could not recover"),
    ):
        recover_runtime_transactions(site_dir)

    assert current.read_text(encoding="utf-8") == "new\n"
    assert transaction_dir.exists()


def test_recovery_replace_failure_keeps_current_runtime_file(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    site_dir.mkdir(parents=True)
    current = site_dir / "demo.py"
    current.write_text("new\n", encoding="utf-8")
    transaction_dir = site_dir.parent / ".transactions" / "interrupted"
    backup = transaction_dir / "backup"
    backup.mkdir(parents=True)
    (backup / "demo.py").write_text("old\n", encoding="utf-8")
    (transaction_dir / "manifest.json").write_text(
        """{
  "state": "committing",
  "backup_paths": ["demo.py"],
  "staged_paths": ["demo.py"]
}
""",
        encoding="utf-8",
    )

    with (
        patch(
            "qwenpaw.package_runtime.os.replace",
            side_effect=PermissionError("restore replace failed"),
        ),
        pytest.raises(RuntimeError, match="Could not recover"),
    ):
        recover_runtime_transactions(site_dir)

    assert current.read_text(encoding="utf-8") == "new\n"
    assert transaction_dir.exists()


def test_recovery_deletes_new_files_only_after_restoring_backups(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    site_dir.mkdir(parents=True)
    restored = site_dir / "demo.py"
    added = site_dir / "added.py"
    restored.write_text("new\n", encoding="utf-8")
    added.write_text("added\n", encoding="utf-8")
    transaction_dir = site_dir.parent / ".transactions" / "interrupted"
    backup = transaction_dir / "backup"
    backup.mkdir(parents=True)
    (backup / "demo.py").write_text("old\n", encoding="utf-8")
    (transaction_dir / "manifest.json").write_text(
        """{
  "state": "committing",
  "backup_paths": ["demo.py"],
  "staged_paths": ["demo.py", "added.py"]
}
""",
        encoding="utf-8",
    )
    original_unlink = Path.unlink

    def fail_added_unlink(path, *args, **kwargs):
        if path == added:
            raise PermissionError("new file is locked")
        return original_unlink(path, *args, **kwargs)

    with (
        patch.object(
            Path,
            "unlink",
            autospec=True,
            side_effect=fail_added_unlink,
        ),
        pytest.raises(RuntimeError, match="Could not recover"),
    ):
        recover_runtime_transactions(site_dir)

    assert restored.read_text(encoding="utf-8") == "old\n"
    assert added.read_text(encoding="utf-8") == "added\n"
    assert transaction_dir.exists()


def test_recover_runtime_transactions_removes_uncommitted_staging(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    transaction_dir = site_dir.parent / ".transactions" / "download"
    staging = transaction_dir / "staging"
    staging.mkdir(parents=True)
    (staging / "partial.whl").write_text("partial", encoding="utf-8")

    recover_runtime_transactions(site_dir)

    assert not transaction_dir.exists()


def test_runtime_write_lock_timeout_does_not_enter_unlocked(tmp_path):
    with patch("qwenpaw.plugins.install_lock.plugin_install_lock") as lock:
        lock.return_value.__enter__.return_value = False
        with pytest.raises(RuntimeError, match="Runtime write lock"):
            with runtime_write_lock(tmp_path / "site", timeout=0):
                pytest.fail("Runtime write lock must not yield after timeout")


def test_read_recovery_does_not_wait_for_active_installer(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    transaction_dir = site_dir.parent / ".transactions" / "active"
    transaction_dir.mkdir(parents=True)

    with patch("qwenpaw.plugins.install_lock.plugin_install_lock") as lock:
        lock.return_value.__enter__.return_value = False
        recover_runtime_if_needed(site_dir)

    assert transaction_dir.exists()
    assert lock.call_args.kwargs["timeout"] == 0.0


def test_recovery_preserves_corrupt_manifest_and_reports_error(tmp_path):
    site_dir = tmp_path / "bucket" / "site"
    transaction_dir = site_dir.parent / ".transactions" / "broken"
    transaction_dir.mkdir(parents=True)
    (transaction_dir / "manifest.json").write_text(
        "not-json",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Could not recover"):
        recover_runtime_transactions(site_dir)

    assert transaction_dir.exists()


def test_verify_runtime_requirements_uses_clean_child_process(tmp_path):
    _write_distribution(
        tmp_path,
        name="demo-package",
        version="1.0",
        files={"demo_package.py": "value = 1\n"},
    )

    verify_runtime_requirements(
        sys.executable,
        tmp_path,
        ["demo-package==1.0"],
    )


@pytest.mark.parametrize(
    ("name", "version", "files"),
    [
        ("PyJWT", "2.13.0", {"jwt/__init__.py": "value = 1\n"}),
        ("single-package", "1.0", {"single_module.py": "value = 1\n"}),
        ("metadata-package", "1.0", {}),
    ],
)
def test_verify_runtime_requirements_infers_imports(
    tmp_path,
    name,
    version,
    files,
):
    _write_distribution(
        tmp_path,
        name=name,
        version=version,
        files=files,
    )

    verify_runtime_requirements(
        sys.executable,
        tmp_path,
        [f"{name}=={version}"],
    )


def test_verify_runtime_requirements_accepts_one_import_candidate(tmp_path):
    _write_distribution(
        tmp_path,
        name="multi-package",
        version="1.0",
        files={
            "broken/__init__.py": "raise RuntimeError('broken')\n",
            "working/__init__.py": "value = 1\n",
        },
    )

    verify_runtime_requirements(
        sys.executable,
        tmp_path,
        ["multi-package==1.0"],
    )


def test_verify_runtime_requirements_rejects_failed_candidates(tmp_path):
    _write_distribution(
        tmp_path,
        name="broken-package",
        version="1.0",
        files={"broken/__init__.py": "raise RuntimeError('broken')\n"},
    )

    with pytest.raises(
        RuntimeError,
        match="Could not import Runtime distribution broken-package",
    ):
        verify_runtime_requirements(
            sys.executable,
            tmp_path,
            ["broken-package==1.0"],
        )


def test_verify_runtime_requirements_keeps_payload_off_command_line(tmp_path):
    secret = "https://user:password@example.com/demo.whl"
    verified = {
        "demo-package": {
            "versions": ["1.0"],
            "imported": False,
        },
    }
    completed = subprocess.CompletedProcess(
        [],
        0,
        "QWENPAW_RUNTIME_VERIFY:" + json.dumps(verified),
        "",
    )
    with patch(
        "qwenpaw.package_runtime.subprocess.run",
        return_value=completed,
    ) as run:
        verify_runtime_requirements(
            sys.executable,
            tmp_path,
            [f"demo-package @ {secret}"],
        )

    command = run.call_args.args[0]
    assert secret not in " ".join(command)
    assert secret not in run.call_args.kwargs["input"]
    assert "from packaging" not in command[-1]
