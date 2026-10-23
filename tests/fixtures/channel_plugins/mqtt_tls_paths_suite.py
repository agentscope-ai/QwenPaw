"""MQTT TLS paths retain backend cwd semantics across real worker launch."""

from copy import deepcopy
import os
from pathlib import Path
import shutil

import psutil
import pytest

from extension_process_suite import runtime
from extension_sample import ROOT
from g2_lifecycle_suite import certificate_files
from g2_mqtt_broker import Broker
from g2_official_process_suite import forbid_host_sdk_import, mqtt
from qwenpaw.plugins import official_execution_context

__all__ = ["runtime", "forbid_host_sdk_import"]

TLS_FILES = {
    "tls_ca_certs": "tls/authority.pem",
    "tls_certfile": "tls/identity.pem",
    "tls_keyfile": "tls/private.key",
}


@pytest.fixture(autouse=True)
def current_host_source():
    assert Path(official_execution_context.__file__).resolve() == (
        ROOT / "src/qwenpaw/plugins/official_execution_context.py"
    )


@pytest.mark.parametrize(
    "kind", ["relative", "absolute", "home", "none", "empty"]
)
def test_tls_path_projection_is_detached_and_uses_backend_cwd(
    tmp_path, monkeypatch, kind
):
    backend, state, workspace, ambient = (
        tmp_path / name
        for name in ("backend", "state", "workspace", "ambient")
    )
    ambient.mkdir()
    monkeypatch.chdir(ambient)
    values, expected = {}, {}
    for field, filename in TLS_FILES.items():
        if kind == "relative":
            values[field] = filename
            expected[field] = str(backend / filename)
        elif kind == "absolute":
            values[field] = expected[field] = str(tmp_path / filename)
        elif kind == "home":
            values[field] = "~/" + filename
            expected[field] = str(Path.home() / filename)
        else:
            values[field] = expected[field] = None if kind == "none" else ""
    values["options"] = {"labels": ["original"]}
    original = deepcopy(values)

    projected, environment = (
        official_execution_context.project_official_execution(
            "mqtt",
            values,
            working_dir=backend,
            legacy_state_dir=state,
            workspace_dir=workspace,
            environment={},
        )
    )

    assert {field: projected[field] for field in TLS_FILES} == expected
    assert environment == {}
    assert values == original
    projected["options"]["labels"].append("execution-only")
    assert values == original


@pytest.mark.asyncio
async def test_relative_tls_files_authenticate_and_publish_in_real_child(
    runtime, tmp_path, monkeypatch
):
    backend = tmp_path / "backend"
    certificates = backend / "tls"
    certificates.mkdir(parents=True)
    certificate, key, context = certificate_files(certificates)
    shutil.copyfile(certificate, backend / TLS_FILES["tls_ca_certs"])
    shutil.copyfile(certificate, backend / TLS_FILES["tls_certfile"])
    shutil.copyfile(key, backend / TLS_FILES["tls_keyfile"])
    monkeypatch.chdir(backend)
    original = dict(TLS_FILES)
    broker = Broker(tls_context=context)
    try:
        rt = await mqtt(runtime, broker, tls_enabled=True, **original)
        spec = rt.channel._launch_spec
        state = Path(os.environ["QWENPAW_WORKING_DIR"])
        assert len({backend, state, rt.ws.workspace_dir, spec.code_root}) == 4
        assert {field: spec.config[field] for field in TLS_FILES} == {
            "tls_ca_certs": str(backend / "tls/authority.pem"),
            "tls_certfile": str(backend / "tls/identity.pem"),
            "tls_keyfile": str(backend / "tls/private.key"),
        }
        saved = rt.ws.config.channels.mqtt.model_dump()
        assert {field: saved[field] for field in TLS_FILES} == original
        assert original == TLS_FILES
        pid = rt.process.health_snapshot()["pid"]
        assert pid and pid != os.getpid()
        assert Path(psutil.Process(pid).cwd()) == spec.code_root
        plugin_file = Path("qwenpaw_channel_mqtt/platform.py")
        assert (spec.code_root / plugin_file).read_bytes() == (
            ROOT / "plugins/channel/mqtt" / plugin_file
        ).read_bytes()

        await rt.channel.send_content_parts(
            "device", [{"type": "text", "text": "relative TLS"}], {}
        )

        assert broker.peer_certificates and all(broker.peer_certificates)
        assert broker.publishes == [("out/device", "relative TLS", 2)]
        assert broker.handshake_errors == []
    finally:
        broker.close()
