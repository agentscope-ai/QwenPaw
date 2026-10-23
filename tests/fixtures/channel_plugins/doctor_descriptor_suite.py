"""Doctor actual Loader/management; \
external reachability alone is controlled."""

import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def doctor_host(tmp_path, monkeypatch):
    from qwenpaw.cli import doctor_connectivity as dc
    from qwenpaw.config.config import Config, ChannelConfig
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.official_channels import bundled_channel_source
    from qwenpaw.app.channels.management import ChannelManagementService
    from qwenpaw.plugins.execution.process import PluginProcess

    installed = tmp_path / "installed"
    installed.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: installed
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    prior = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    registry.channel_runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        qwenpaw_version="2.2.2b6",
        selected_channels=None,
        startup_timeout=5,
        shutdown_timeout=1,
    )
    calls = []
    starts = []
    cleanup = []
    sources = {}
    real_execute = ChannelManagementService.execute

    async def execute(
        self, workspace_id, channel_key, operation, *args, **kwargs
    ):
        calls.append((workspace_id, channel_key, operation))
        return await real_execute(
            self, workspace_id, channel_key, operation, *args, **kwargs
        )

    monkeypatch.setattr(ChannelManagementService, "execute", execute)
    real_start = PluginProcess._start

    async def start(self, *args, **kwargs):
        value = await real_start(self, *args, **kwargs)
        starts.append(self.health_snapshot()["pid"])
        return value

    monkeypatch.setattr(PluginProcess, "_start", start)
    real_close = ChannelManagementService.aclose

    async def close(self):
        await real_close(self)
        cleanup.append(True)

    monkeypatch.setattr(ChannelManagementService, "aclose", close)

    def make(channels):
        for key in channels:
            if key in {"console", "missing_extra"}:
                continue
            with bundled_channel_source(
                "azure-bot" if key == "azure_bot" else key
            ) as source:
                shutil.copytree(source, installed / key)
                sources[key] = json.loads(
                    (source / "channel.json").read_text()
                )
        values = {
            name: {"enabled": False} for name in ChannelConfig.model_fields
        }
        values.update(channels)
        (workspace / "agent.json").write_text(
            json.dumps({"id": "doctor", "channels": values})
        )
        cfg = Config.model_validate(
            {
                "channels": values,
                "agents": {
                    "profiles": {
                        "doctor": {
                            "id": "doctor",
                            "workspace_dir": str(workspace),
                        }
                    }
                },
            }
        )
        return cfg

    try:
        yield SimpleNamespace(
            make=make,
            dc=dc,
            calls=calls,
            starts=starts,
            cleanup=cleanup,
            registry=registry,
            sources=sources,
        )
    finally:
        PluginRegistry._instance = prior


def test_official_nonverify_uses_generic_probes_without_management(
    doctor_host, monkeypatch
):
    h = doctor_host
    cfg = h.make(
        {
            "mqtt": {"enabled": True, "host": "broker.test", "port": 1883},
            "xiaoyi": {"enabled": True},
            "console": {"enabled": True},
            "imessage": {"enabled": True},
        }
    )
    tcp = []
    monkeypatch.setattr(
        h.dc,
        "_tcp_check",
        lambda host, port, timeout: tcp.append((host, port, timeout))
        or "controlled refusal",
    )
    notes = h.dc.collect_deep_channel_connectivity_notes(cfg, 3)
    print(
        "DOCTOR_OBSERVATION "
        + json.dumps(
            {
                "notes": notes,
                "tcp": tcp,
                "manage_calls": h.calls,
                "starts": h.starts,
                "cleanup": h.cleanup,
            }
        ),
        flush=True,
    )
    assert all(
        "channel.management.verify.v1" not in h.sources[k]["capabilities"]
        for k in ("mqtt", "xiaoyi", "imessage")
    )
    assert h.calls == []
    assert h.starts == [] and h.cleanup == [True]
    assert tcp == [
        ("broker.test", 1883, 3),
        ("hag.cloud.huawei.com", 443, 3),
        ("116.63.174.231", 443, 3),
    ]
    assert notes == [
        "doctor: mqtt: TCP broker.test:1883 — controlled refusal",
        "doctor: xiaoyi: TCP hag.cloud.huawei.com:443 "
        "(primary) — controlled refusal",
        "doctor: xiaoyi: TCP 116.63.174.231:443 (backup) — controlled refusal",
    ]


def test_official_schema_extra_without_verify_is_not_missing_class(
    doctor_host,
):
    h = doctor_host
    cfg = h.make(
        {"azure_bot": {"enabled": True}, "console": {"enabled": True}}
    )
    notes = h.dc.collect_deep_channel_connectivity_notes(cfg, 3)
    print(
        "DOCTOR_EXTRA "
        + json.dumps(
            {"notes": notes, "manage_calls": h.calls, "starts": h.starts}
        ),
        flush=True,
    )
    assert (
        h.registry.get_channel_catalog_entry("azure_bot").description_record
        is not None
    )
    assert (
        "channel.management.verify.v1"
        not in h.sources["azure_bot"]["capabilities"]
    )
    assert h.calls == [] and h.starts == [] and h.cleanup == [True]
    assert (
        notes == []
    )  # No connectivity claim: no supported verifier or generic probe.


def test_missing_extra_still_has_actionable_diagnostic(doctor_host):
    h = doctor_host
    cfg = h.make(
        {"missing_extra": {"enabled": True}, "console": {"enabled": True}}
    )
    notes = h.dc.collect_deep_channel_connectivity_notes(cfg, 3)
    assert (
        len(notes) == 1
        and "missing_extra" in notes[0]
        and "not in registry" in notes[0]
    )
    assert h.calls == [] and h.starts == [] and h.cleanup == [True]


@pytest.mark.parametrize(
    "status,cleanup_error,expected",
    [
        (200, False, []),
        (
            403,
            False,
            ["doctor: wechat: reachability — PLATFORM_REQUEST_FAILED"],
        ),
        (
            200,
            True,
            ["channel management cleanup — MANAGEMENT_CLEANUP_FAILED"],
        ),
    ],
)
def test_supported_wechat_uses_actual_management_worker_and_preserves_errors(
    doctor_host, monkeypatch, status, cleanup_error, expected
):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import psutil
    from qwenpaw.app.channels.management import (
        ChannelManagementService,
        ManagementError,
    )

    h = doctor_host
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(status)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, name="doctor-test-http"
    )
    thread.start()
    try:
        cfg = h.make(
            {
                "wechat": {
                    "enabled": True,
                    "base_url": f"http://127.0.0.1:{server.server_port}",
                },
                "console": {"enabled": True},
            }
        )
        if cleanup_error:
            real_close = ChannelManagementService.aclose

            async def close_then_report(self):
                await real_close(self)
                raise ManagementError("MANAGEMENT_CLEANUP_FAILED")

            monkeypatch.setattr(
                ChannelManagementService, "aclose", close_then_report
            )
        generic = []
        monkeypatch.setattr(
            h.dc, "_http_get_ok", lambda *args: generic.append(args) or None
        )
        notes = h.dc.collect_deep_channel_connectivity_notes(cfg, 3)
        print(
            "DOCTOR_WECHAT "
            + json.dumps(
                {
                    "status": status,
                    "notes": notes,
                    "http": requests,
                    "calls": h.calls,
                    "pids": h.starts,
                    "cleanup": h.cleanup,
                }
            ),
            flush=True,
        )
        assert (
            "channel.management.verify.v1"
            in h.sources["wechat"]["capabilities"]
        )
        assert h.calls == [("doctor", "wechat", "connection.verify")]
        assert requests == ["/"] and generic == []
        assert len(h.starts) == 1 and not psutil.pid_exists(h.starts[0])
        assert h.cleanup == [True] and notes == expected
        assert h.registry.runtime_owners.leases() == ()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()
