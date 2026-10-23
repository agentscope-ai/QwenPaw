"""Real generic management producer for FD/DD-shaped session regressions.

The sample remains a third-party owner. Only its external local HTTP response
is controlled; Loader, Service, Session, child worker and RPC are production.
"""

from importlib import import_module
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

import management_process_suite as management_fixture
from management_process_suite import (
    GUARD,
    KEY,
    local_management_http,
    management_runtime,
)
from wechat_w2_config_support import write_profiles
from wechat_w2_scope_suite import request


@pytest.fixture(autouse=True)
def g3_host_import_boundary(monkeypatch):
    original = GUARD.blocks
    hosts = {
        "qwenpaw.app.channels.qrcode_sessions",
        "qwenpaw.app.channels.wechat_auth_custody",
        "qwenpaw.app.channels.qrcode_auth_handler",
    }
    monkeypatch.setattr(
        GUARD,
        "blocks",
        lambda name: name not in hosts and original(name),
    )
    yield
    assert not GUARD.attempts


@pytest_asyncio.fixture
async def g3_qr(
    management_runtime, local_management_http, tmp_path, monkeypatch
):
    original = management_fixture.management_sample_source

    def source(*args, **kwargs):
        sample = original(*args, **kwargs)
        path = sample.source / "channel.json"
        descriptor = json.loads(path.read_text())
        descriptor["config_schema"]["properties"]["media_dir"] = {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        }
        descriptor["config_fields"].append("media_dir")
        path.write_text(json.dumps(descriptor))
        driver_path = sample.source / KEY / "driver.py"
        driver_text = driver_path.read_text()
        marker = '"config": config,'
        assert driver_text.count(marker) == 1
        driver_path.write_text(
            driver_text.replace(
                marker,
                marker
                + '\n                "options": data["parameters"].get("options"),',
            )
        )
        return sample

    monkeypatch.setattr(management_fixture, "management_sample_source", source)
    rt = await management_runtime()
    api = import_module("qwenpaw.app.channels.qrcode_sessions")
    sessions = api.ChannelQRCodeSessions(rt.loader, rt.service)

    def scope(**extra):
        write_profiles(
            tmp_path,
            monkeypatch,
            KEY,
            {
                "enabled": False,
                "host": local_management_http.host,
                "port": local_management_http.port,
                **extra,
            },
        )
        return api.resolve_channel_management_scope(request(header="A"), KEY)

    try:
        yield SimpleNamespace(
            rt=rt, http=local_management_http, sessions=sessions, scope=scope
        )
    finally:
        await sessions.aclose()


__all__ = [
    "g3_host_import_boundary",
    "g3_qr",
    "local_management_http",
    "management_runtime",
]
