"""Docker upgrade contracts using a fresh installed wheel, not a container.

All 18 source mappings are exercised; real SDK network delivery uses MQTT.
Only the entrypoint's pre-server phase and channel boot phases are executed.
"""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import wheel_upgrade_support as support

OWNERS = {
    **{
        key: key
        for key in (
            "telegram",
            "slack",
            "discord",
            "mqtt",
            "mattermost",
            "dingtalk",
            "feishu",
            "qq",
            "wecom",
            "yuanbao",
            "xiaoyi",
            "wechat",
            "matrix",
            "imessage",
            "onebot",
            "voice",
            "sip",
        )
    },
    "azure_bot": "azure-bot",
}
PROBE = Path(__file__).with_name("docker_upgrade_probe.py")


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    root = tmp_path_factory.mktemp("docker-new-image")
    sdk = support.installed_sdk_wheel(root / "warehouse")
    candidate = support.build_candidate(root)
    python = support.create_environment(root / "venv")
    env = support.clean_environment(root)
    env["PIP_FIND_LINKS"] = str(sdk.parent)
    # Match Docker's SDK extra with real installed distributions, offline.
    support.run(
        [python, "-I", "-m", "pip", "install", f"{candidate}[channels]"],
        env=env,
        cwd=root,
    )
    return python


def persisted(root, location, *, mqtt=None, policy=None):
    host = root / "host"
    host.mkdir()
    workspace = host / "workspaces/default"
    channels = (
        {"mqtt": mqtt}
        if mqtt
        else {key: {"enabled": True, "bot_prefix": "historic-prefix"} for key in OWNERS}
    )
    if policy == "disabled":
        for values in channels.values():
            values["enabled"] = False
    elif policy == "mixed":
        for key, values in channels.items():
            values["enabled"] = key == "mqtt"
    raw = {"channels": channels}
    original = None
    if location == "workspace":
        workspace.mkdir(parents=True)
        agent = workspace / "agent.json"
        agent.write_text(
            json.dumps(
                {
                    "id": "default",
                    "name": "Historic Agent",
                    "workspace_dir": str(workspace),
                    **raw,
                }
            )
        )
        original = agent.read_bytes()
        raw = {
            "agents": {
                "profiles": {
                    "default": {"id": "default", "workspace_dir": str(workspace)}
                }
            }
        }
    if policy == "plugin-disabled":
        raw["plugins"] = {owner: {"enabled": False} for owner in OWNERS.values()}
    if policy == "uninstalled":
        raw["channel_plugin_state"] = {"uninstalled": list(OWNERS.values())}
    (host / "config.json").write_text(json.dumps(raw))
    expected = {
        "owners": OWNERS,
        "installed": list(OWNERS) if policy != "uninstalled" else [],
        "preset": "channels-full",
        "environment_preset": "channels-full",
        "uninstalled": list(OWNERS) if policy == "uninstalled" else [],
        "disabled": list(OWNERS.values()) if policy == "plugin-disabled" else [],
        "transport": mqtt is not None,
        "mqtt": mqtt,
    }
    expectation = root / "expected.json"
    expectation.write_text(json.dumps(expected))
    return host, workspace / "agent.json", original, channels, expectation


def launch(image, root, expectation, *, preset="channels-full"):
    env = support.clean_environment(root)
    if preset is not None:
        env["QWENPAW_CHANNEL_PRESET"] = preset
    env["QWENPAW_DISABLED_CHANNELS"] = "imessage"
    # Run actual policy/init logic; the remaining lines require Linux supervisor.
    entrypoint = (support.ROOT / "deploy/entrypoint.sh").read_text()
    prefix = entrypoint.split("export QWENPAW_PORT=", 1)[0]
    return [
        "/bin/sh",
        "-c",
        prefix + '\nexec "$@"\n',
        "docker-acceptance",
        str(image),
        "-I",
        "-B",
        str(PROBE),
        str(expectation),
    ], env


def assert_saved(host, agent, original, channels):
    saved = json.loads(agent.read_text())["channels"]
    for key, values in channels.items():
        assert all(saved[key][name] == value for name, value in values.items()), (
            key,
            saved[key],
            values,
        )
    if original is not None:
        assert agent.read_bytes() == original
    else:
        root_saved = json.loads((host / "config.json").read_text())["channels"]
        for key, values in channels.items():
            assert all(root_saved[key][name] == value for name, value in values.items())


@pytest.mark.parametrize("location", ["root", "workspace"])
@pytest.mark.parametrize("policy", [None, "disabled", "plugin-disabled", "uninstalled"])
def test_full_image_migrates_all18_and_respects_saved_policy(
    image, tmp_path, location, policy
):
    host, agent, original, channels, expectation = persisted(
        tmp_path, location, policy=policy
    )
    previous = None
    for generation in (1, 2):
        args, env = launch(image, tmp_path, expectation)
        result = support.run(args, env=env, cwd=tmp_path)
        observed = json.loads(result.stdout.splitlines()[-1])
        assert_saved(host, agent, original, channels)
        assert observed["migrated"] is (location == "root" and generation == 1)
        if previous:
            assert observed["pid"] != previous["pid"]
            assert observed["sources"] == previous["sources"]
        previous = observed


@pytest.mark.parametrize("location", ["root", "workspace"])
@pytest.mark.parametrize(
    "policy", [None, "disabled", "mixed", "plugin-disabled", "uninstalled"]
)
def test_default_light_image_migrates_enabled_legacy_sources_only(
    image, tmp_path, location, policy
):
    host, agent, original, channels, expectation = persisted(
        tmp_path, location, policy=policy
    )
    expected = json.loads(expectation.read_text())
    expected.update(preset="light", environment_preset="light")
    if policy == "disabled":
        expected["installed"] = []
    elif policy == "mixed":
        expected["installed"] = ["mqtt"]
    expectation.write_text(json.dumps(expected))
    previous = None
    for generation in (1, 2):
        args, env = launch(image, tmp_path, expectation, preset=None)
        result = support.run(args, env=env, cwd=tmp_path)
        observed = json.loads(result.stdout.splitlines()[-1])
        assert_saved(host, agent, original, channels)
        assert observed["migrated"] is (location == "root" and generation == 1)
        if previous:
            assert observed["pid"] != previous["pid"]
            assert observed["sources"] == previous["sources"]
        previous = observed


@pytest.mark.parametrize("location", ["root", "workspace"])
@pytest.mark.parametrize("saved_preset", ["channels-full", "light"])
def test_default_light_image_preserves_saved_policy_and_existing_sources(
    image, tmp_path, location, saved_preset
):
    host, agent, original, channels, expectation = persisted(
        tmp_path, location, policy="disabled"
    )
    config_path = host / "config.json"
    config = json.loads(config_path.read_text())
    config["channel_plugin_state"] = {
        "version": 1,
        "preset": "channels-full",
        "legacy_captured": list(OWNERS),
    }
    config_path.write_text(json.dumps(config))
    expected = json.loads(expectation.read_text())
    expected["environment_preset"] = "light"
    expectation.write_text(json.dumps(expected))
    args, env = launch(image, tmp_path, expectation, preset=None)
    result = support.run(args, env=env, cwd=tmp_path)
    first = json.loads(result.stdout.splitlines()[-1])
    assert_saved(host, agent, original, channels)
    config = json.loads(config_path.read_text())
    config["channel_plugin_state"]["preset"] = saved_preset
    config_path.write_text(json.dumps(config))
    expected["preset"] = saved_preset
    expectation.write_text(json.dumps(expected))
    source = host / "plugins/mqtt/qwenpaw_channel_mqtt/driver.py"
    source.write_bytes(source.read_bytes() + b"\n# User-maintained local source.\n")
    retained = {
        **first["sources"],
        "mqtt/qwenpaw_channel_mqtt/driver.py": hashlib.sha256(
            source.read_bytes()
        ).hexdigest(),
    }
    result = support.run(args, env=env, cwd=tmp_path)
    second = json.loads(result.stdout.splitlines()[-1])
    assert second["pid"] != first["pid"]
    assert second["sources"] == retained
    assert_saved(host, agent, original, channels)


class Broker:
    """Minimal MQTT 3.1.1 peer validating saved auth and custom topics."""

    def __init__(self):
        self.connections, self.sent, self.errors = 0, [], []

    async def serve(self, reader, writer):
        try:
            while True:
                header = (await reader.readexactly(1))[0]
                length, multiplier = 0, 1
                while True:
                    byte = (await reader.readexactly(1))[0]
                    length += (byte & 127) * multiplier
                    if byte < 128:
                        break
                    multiplier *= 128
                body = await reader.readexactly(length)
                kind = header >> 4
                if kind == 1:
                    offset = 10
                    fields = []
                    while offset < len(body):
                        size = int.from_bytes(body[offset : offset + 2], "big")
                        fields.append(body[offset + 2 : offset + 2 + size].decode())
                        offset += 2 + size
                    assert body[7] & 0xC0 == 0xC0
                    assert fields[1:] == ["historic-user", "historic-password"]
                    self.connections += 1
                    writer.write(b"\x20\x02\x00\x00")
                elif kind == 8:
                    size = int.from_bytes(body[2:4], "big")
                    assert body[4 : 4 + size].decode() == "historic/in/+"
                    assert body[4 + size] == 0
                    writer.write(b"\x90\x03" + body[:2] + b"\x00")
                    topic = b"historic/in/client17"
                    payload = (
                        b'{"text":"historic inbound","redirect_client_id":"client17"}'
                    )
                    packet = len(topic).to_bytes(2, "big") + topic + payload
                    assert len(packet) < 128
                    writer.write(b"\x30" + bytes([len(packet)]) + packet)
                elif kind == 3:
                    size = int.from_bytes(body[:2], "big")
                    self.sent.append(
                        (body[2 : 2 + size].decode(), body[2 + size :].decode())
                    )
                elif kind == 12:
                    writer.write(b"\xd0\x00")
                elif kind == 14:
                    return
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:
            self.errors.append(repr(exc))
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["root", "workspace"])
async def test_new_image_boots_unchanged_mqtt_and_fresh_host_restart(
    image, tmp_path, location
):
    broker = Broker()
    server = await asyncio.start_server(broker.serve, "127.0.0.1", 0)
    mqtt = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": server.sockets[0].getsockname()[1],
        "username": "historic-user",
        "password": "historic-password",
        "qos": 0,
        "subscribe_topic": "historic/in/+",
        "publish_topic": "historic/out/{client_id}",
    }
    host, agent, original, channels, expectation = persisted(
        tmp_path, location, mqtt=mqtt
    )
    previous = None
    try:
        for generation in (1, 2):
            args, env = launch(image, tmp_path, expectation)
            process = await asyncio.create_subprocess_exec(
                *args,
                env=env,
                cwd=tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), 90)
            assert process.returncode == 0, (
                stdout.decode()[-8000:] + stderr.decode()[-12000:]
            )
            observed = json.loads(stdout.decode().splitlines()[-1])
            assert observed["child"] and broker.connections == generation
            assert (
                broker.sent
                == [("historic/out/client17", "docker-upgrade-answer")] * generation
            )
            assert broker.errors == []
            assert_saved(host, agent, original, channels)
            if previous:
                assert observed["pid"] != previous["pid"]
                assert observed["child"] != previous["child"]
                assert observed["sources"] == previous["sources"]
            previous = observed
    finally:
        server.close()
        await server.wait_closed()
