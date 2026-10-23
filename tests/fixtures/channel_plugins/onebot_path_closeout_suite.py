"""Saved OneBot media paths retain host meaning across worker separation."""

from pathlib import Path

from onebot_contract_suite import official_onebot_proxy

__all__ = ["official_onebot_proxy"]


def test_official_relative_media_path_keeps_legacy_host_cwd(
    official_onebot_proxy, tmp_path, monkeypatch
):
    # Old in-process OneBot resolves this saved relative path in host cwd.
    # Worker cwd is code_root; the factory must bind the old host meaning.
    host = tmp_path / "host-cwd"
    host.mkdir()
    monkeypatch.chdir(host)
    saved = {"enabled": False, "media_dir": "old-relative-media"}
    proxy = official_onebot_proxy(saved)
    assert saved == {"enabled": False, "media_dir": "old-relative-media"}
    assert proxy.channel_process.health_snapshot()["pid"] is None
    projected = proxy._launch_spec.config["media_dir"]
    assert projected == str(host / "old-relative-media")
    assert Path(projected).is_absolute()
    assert not (host / "old-relative-media").exists()
