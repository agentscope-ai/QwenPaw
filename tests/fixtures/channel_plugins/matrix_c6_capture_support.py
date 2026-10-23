"""Raw persisted fixture + real host capture/factory, no fabricated owner."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
BOT = "@bot:example.com"
DEVICE = "SERVER-DEVICE"
OLD_TOKEN = "old-cached-token-never-transmit"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def raw_case(tmp_path, homeserver, *, ambiguous=False):
    root = tmp_path / "legacy"
    workspace = tmp_path / "A"
    workspace.mkdir(parents=True)
    config = {
        "enabled": True,
        "homeserver": homeserver,
        "user_id": BOT,
        "password": "explicit-password",
        "access_token": "",
    }
    profiles = {"A": {"id": "A", "workspace_dir": str(workspace)}}
    if ambiguous:
        other = tmp_path / "B"
        other.mkdir()
        profiles["B"] = {"id": "B", "workspace_dir": str(other)}
    write_json(
        root / "config.json",
        {
            "channels": {"matrix": config},
            "agents": {"active_agent": "A", "profiles": profiles},
        },
    )
    write_json(
        root / "matrix_auth_state.json",
        {"user_id": BOT, "device_id": DEVICE, "access_token": OLD_TOKEN},
    )
    (root / "matrix_sync_token").write_bytes(b"legacy-batch")
    crypto = root / "matrix_crypto_store"
    crypto.mkdir()
    (crypto / f"{BOT}_{DEVICE}.db").write_bytes(b"opaque-no-olm-claim")
    return root, workspace, config


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def capture(root):
    from qwenpaw.plugins.matrix_legacy import capture_matrix_legacy

    return capture_matrix_legacy(
        config_path=root / "config.json",
        legacy_state_dir=root,
        working_dir=root.parent,
    )


def factory_values(root, workspace, config, monkeypatch):
    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    import qwenpaw.constant as constants

    monkeypatch.setattr(constants, "WORKING_DIR", root)
    source = ROOT / "plugins/channel/matrix"
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text())
        ),
    )

    async def unused_process(_request):
        raise AssertionError("Unstarted factory must not call an Agent")
        yield

    proxy = description.create_proxy(
        unused_process,
        config,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="matrix-c6-capture",
        generation=1,
        qwenpaw_version=__version__,
        workspace_dir=workspace,
    )
    return dict(proxy._launch_spec.config)
