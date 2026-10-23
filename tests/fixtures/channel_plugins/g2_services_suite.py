"""Verify local test services with real SDKs before blaming plugin workers."""

import importlib.metadata
import subprocess
import sys
import threading

import pytest

from g2_mqtt_broker import Broker
from g2_lifecycle_suite import (
    tls_certificate,
    copied_paho_with_close_fault,
    copied_httpx_with_close_fault,
)


@pytest.mark.parametrize("transport", ["tcp", "websockets", "tls"])
def test_real_paho_transport_fixture_confirms_qos2(transport, tls_certificate):
    import paho.mqtt.client as paho

    certificate, key, context = tls_certificate
    broker = Broker(
        tls_context=context if transport == "tls" else None,
        websocket=transport == "websockets",
    )
    client = paho.Client(
        paho.CallbackAPIVersion.VERSION2,
        client_id="g2-fixture",
        clean_session=False,
        transport="websockets" if transport == "websockets" else "tcp",
    )
    client.username_pw_set("robot", "secret")
    if transport == "tls":
        client.tls_set(
            ca_certs=str(certificate),
            certfile=str(certificate),
            keyfile=str(key),
        )
    connected = threading.Event()
    client.on_connect = lambda *_: connected.set()
    try:
        client.connect("127.0.0.1", broker.port)
        client.loop_start()
        assert connected.wait(2)
        info = client.publish("out/device", "real wire", qos=2)
        info.wait_for_publish(2)
        assert info.is_published()
        assert broker.publishes == [("out/device", "real wire", 2)]
        assert broker.connect_packets[0]["username"] == "robot"
        assert broker.connect_packets[0]["password"] == "secret"
        assert broker.connect_packets[0]["clean_session"] is False
        if transport == "tls":
            assert broker.peer_certificates and all(broker.peer_certificates)
    finally:
        client.disconnect()
        client.loop_stop()
        broker.close()


@pytest.mark.parametrize("name", ["paho-mqtt", "httpx"])
def test_copied_sdk_fault_keeps_real_distribution_version_and_origin(
    tmp_path, name
):
    factory = (
        copied_paho_with_close_fault
        if name == "paho-mqtt"
        else copied_httpx_with_close_fault
    )
    site, fault, entered = factory(tmp_path)
    fault.touch()
    snippet = (
        "import paho.mqtt.client as sdk; client=sdk.Client(sdk.CallbackAPIVersion.VERSION2); client.loop_stop()"
        if name == "paho-mqtt"
        else "import httpx as sdk; import asyncio; asyncio.run(sdk.AsyncClient().aclose())"
    )
    code = f"""import sys, importlib.metadata
from pathlib import Path
sys.path.insert(0, {str(site)!r})
assert importlib.metadata.version({name!r}) == {importlib.metadata.version(name)!r}
try:
    {snippet}
except OSError as exc:
    assert 'controlled external' in str(exc)
else:
    raise AssertionError('SDK boundary fault was not exercised')
assert Path(sdk.__file__).is_relative_to({str(site)!r})
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert entered.exists()
