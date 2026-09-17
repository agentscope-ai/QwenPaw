"""Snapshots preserve submitted bytes and reject unsafe filesystem entries."""

import os
import pytest


def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: sample\ndescription: sample\n---\nContent A", encoding="utf-8"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "run.py").write_text("print('A')", encoding="utf-8")
    return root


def test_snapshot_freezes_all_files_and_detects_tampering(tmp_path):
    from qwenpaw.skills.snapshots import SnapshotStore

    root = source(tmp_path)
    store = SnapshotStore(tmp_path / "snapshots")
    first = store.capture(root, "sample")
    (root / "scripts" / "run.py").write_text("print('B')", encoding="utf-8")
    second = store.capture(root, "sample")
    assert first.content_hash != second.content_hash
    fixed = store.verify(first.snapshot_key, first.content_hash)
    assert (fixed / "scripts" / "run.py").read_text() == "print('A')"
    (fixed / "SKILL.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot_integrity_failed"):
        store.verify(first.snapshot_key, first.content_hash)


def test_snapshot_rejects_external_link(tmp_path):
    from qwenpaw.skills.snapshots import SnapshotStore

    root = source(tmp_path)
    try:
        (root / "references").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import subprocess

        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root / "references"), str(tmp_path)],
            check=True,
            capture_output=True,
        )
    with pytest.raises(ValueError, match="unsafe_skill_path"):
        SnapshotStore(tmp_path / "snapshots").capture(root, "sample")


def test_snapshot_rejects_private_files_and_untrusted_key(tmp_path):
    from qwenpaw.skills.snapshots import SnapshotStore

    root = source(tmp_path)
    (root / "config.json").write_text('{"token":"private"}', encoding="utf-8")
    store = SnapshotStore(tmp_path / "snapshots")
    with pytest.raises(ValueError, match="private_skill_file"):
        store.capture(root, "sample")
    with pytest.raises(ValueError, match="invalid_snapshot_key"):
        store.verify("../source", "0" * 64)


@pytest.mark.parametrize("mode", ["off", "whitelist", "warn"])
@pytest.mark.parametrize(
    "relative", ["SKILL.md", "scripts/run.py", "references/data.bin"]
)
@pytest.mark.parametrize(
    "payload",
    [
        "api_key = '" + "A" * 24 + "'",
        "ghp_" + "B" * 36,
        "-----BEGIN PRIVATE KEY-----\n"
        + "C" * 32
        + "\n"
        + "D" * 32
        + "\n-----END PRIVATE KEY-----",
    ],
)
def test_shared_snapshot_rejects_secrets_despite_normal_scan_settings(
    tmp_path, monkeypatch, mode, relative, payload
):
    from qwenpaw.skills.snapshots import SnapshotStore
    from qwenpaw.config.config import SkillScannerConfig, SkillScannerWhitelistEntry
    import qwenpaw.security.skill_scanner as scanner

    config = SkillScannerConfig(mode="off" if mode == "off" else "warn")
    if mode == "whitelist":
        config.whitelist = [SkillScannerWhitelistEntry(skill_name="sample")]
    monkeypatch.setattr(scanner, "_load_scanner_config", lambda: config)
    root = source(tmp_path)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="shared_skill_credentials_detected"):
        SnapshotStore(tmp_path / "snapshots").capture(root, "sample")
    assert not (tmp_path / "snapshots").exists()


def test_shared_snapshot_allows_environment_references(tmp_path, monkeypatch):
    from qwenpaw.skills.snapshots import SnapshotStore
    from qwenpaw.config.config import SkillScannerConfig
    import qwenpaw.security.skill_scanner as scanner

    monkeypatch.setattr(
        scanner, "_load_scanner_config", lambda: SkillScannerConfig(mode="off")
    )
    root = source(tmp_path)
    (root / "scripts" / "run.py").write_text(
        'api_key = os.getenv("SERVICE_API_KEY")\ntoken = "${SERVICE_ACCESS_TOKEN}"',
        encoding="utf-8",
    )
    store = SnapshotStore(tmp_path / "snapshots")
    saved = store.capture(root, "sample")
    assert store.verify(saved.snapshot_key, saved.content_hash).is_dir()


def test_shared_snapshot_rule_failure_is_closed(tmp_path, monkeypatch):
    from qwenpaw.skills.snapshots import SnapshotStore
    from qwenpaw.security.skill_scanner.analyzers.pattern_analyzer import SecurityRule

    def broken_rule(self, data):
        raise RuntimeError("rule load failed")

    monkeypatch.setattr(SecurityRule, "__init__", broken_rule)
    with pytest.raises(ValueError, match="shared_skill_credential_scan_failed"):
        SnapshotStore(tmp_path / "snapshots").capture(source(tmp_path), "sample")


def test_existing_snapshot_cannot_bypass_mandatory_credential_gate(tmp_path):
    from qwenpaw.skills.snapshots import SnapshotStore, directory_hash

    key = "a" * 32
    root = tmp_path / "snapshots" / key
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("ghp_" + "E" * 36, encoding="utf-8")
    with pytest.raises(ValueError, match="shared_skill_credentials_detected"):
        SnapshotStore(root.parent).verify(key, directory_hash(root))
