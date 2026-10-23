"""Actual official QQ workspace isolation and activated-update rollback."""

import json
import os

import psutil
import pytest

from extension_process_suite import eventually, identity
from qq_closeout_formal_support import (
    official_qq_zip,
    qq_host_import_guard,
    runtime,
)
from qq_native_support import QQExternal
from real_host_runtime import bind_real_runtime

__all__ = ["qq_host_import_guard", "runtime"]


class AccountGateway(QQExternal):
    """Observe native IDENTIFY tokens without replacing the QQ WS protocol."""

    def __init__(self, directory):
        super().__init__(directory)
        self.accounts = {}

    def _gateway(self, connection):
        accounts = self.accounts

        class Observed:
            def __iter__(self):
                for raw in connection:
                    frame = json.loads(raw)
                    if frame["op"] == 2:
                        accounts[frame["d"]["token"]] = self
                    yield raw

            def __getattr__(self, name):
                return getattr(connection, name)

        super()._gateway(Observed())


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    server = AccountGateway(tmp_path).start()

    def token(row):
        return 200, {
            "access_token": row["body"]["appId"],
            "expires_in": 7200,
        }

    # Real native clients request each account's distinct credential/token.
    server.queue("POST", "/token", *([token] * 20))
    monkeypatch.setenv("QQ_API_BASE", server.base)
    monkeypatch.setenv("QQ_TOKEN_URL", server.base + "/token")
    try:
        yield server
    finally:
        server.stop()


async def ready(rt):
    rt.channel = await rt.manager.get_channel("qq")
    assert rt.channel is not None and rt.channel.enabled
    rt.process = rt.channel.channel_process
    await rt.channel._wait_connected()
    return rt.process.health_snapshot()["pid"]


def message(server, app, mid, text, seq=2):
    server.push(
        {
            "op": 0,
            "s": seq,
            "t": "C2C_MESSAGE_CREATE",
            "d": {
                "id": mid,
                "content": text,
                "author": {"user_openid": "same-actor"},
            },
        },
        server.accounts["QQBot " + app],
    )


def sent(server, app):
    return [
        row
        for row in server.rows("/v2/users/same-actor/messages")
        if row["auth"] == "QQBot " + app
    ]


async def exchange(rt, host, server, app, mid, text, seq=2):
    before = len(sent(server, app))
    builds = len(host.builds)
    message(server, app, mid, text, seq)
    await eventually(lambda: len(sent(server, app)) == before + 1)
    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
    assert len(host.builds) == builds + 1
    assert host.builds[-1]["agent"] == "QwenPawAgent"
    assert host.builds[-1]["session_id"] == "qq:c2c:same-actor"
    assert rt.ws.requests[-1].channel_meta["message_id"] == mid
    assert sent(server, app)[-1]["body"] == {
        "markdown": {"content": "isolated actual answer"},
        "msg_type": 2,
        "msg_seq": 1,
        "msg_id": mid,
    }
    return {
        p: p.read_bytes()
        for p in (rt.ws.workspace_dir / "sessions").rglob("*.json")
    }


@pytest.mark.asyncio
async def test_formal_distinct_accounts_same_event_stop_one_keeps_other(
    runtime, accounts, monkeypatch
):
    first = await runtime(
        "qq",
        source_factory=official_qq_zip,
        workspace_name="qq-A",
        app_id="account-A",
        client_secret="secret-A",
    )
    host_a = await bind_real_runtime(
        first, monkeypatch, reply="isolated actual answer"
    )
    second = await runtime(
        "qq",
        existing_loader=first.loader,
        workspace_name="qq-B",
        app_id="account-B",
        client_secret="secret-B",
    )
    host_b = await bind_real_runtime(
        second, monkeypatch, reply="isolated actual answer"
    )
    pid_a, pid_b = await ready(first), await ready(second)
    assert len({pid_a, pid_b, os.getpid()}) == 3
    owners = first.loader.registry.runtime_owners
    leases = [r for r in owners.leases("qq") if r.key.kind == "channel"]
    assert len(leases) == 2
    assert {id(owners.resource(r)) for r in leases} == {
        id(first.channel),
        id(second.channel),
    }
    a_state = await exchange(
        first, host_a, accounts, "account-A", "same-native-id", "A only"
    )
    b_state = await exchange(
        second, host_b, accounts, "account-B", "same-native-id", "B only"
    )
    assert a_state and b_state and set(a_state).isdisjoint(b_state)
    assert all(b"A only" in b and b"B only" not in b for b in a_state.values())
    assert all(b"B only" in b and b"A only" not in b for b in b_state.values())
    assert len(first.ws.requests) == len(second.ws.requests) == 1
    assert {
        (r["body"]["appId"], r["body"]["clientSecret"])
        for r in accounts.rows("/token")
    } == {("account-A", "secret-A"), ("account-B", "secret-B")}
    receipt = await first.manager.stop_one("qq")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == () and not psutil.pid_exists(pid_a)
    assert psutil.pid_exists(pid_b)
    remaining = [r for r in owners.leases("qq") if r.key.kind == "channel"]
    assert (
        len(remaining) == 1 and owners.resource(remaining[0]) is second.channel
    )
    await exchange(
        second, host_b, accounts, "account-B", "after-A-stop", "B survives", 3
    )
    assert len(host_a.builds) == 1 and len(host_b.builds) == 2
    assert {p: p.read_bytes() for p in a_state} == a_state
    assert len(sent(accounts, "account-A")) == 1
    receipt = await second.manager.stop_one("qq")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(pid_b) and not owners.leases("qq")


@pytest.mark.asyncio
async def test_connected_candidate_failure_restores_agent_and_state(
    runtime, accounts, monkeypatch, tmp_path
):
    rt = await runtime(
        "qq",
        source_factory=official_qq_zip,
        app_id="account-rollback",
        client_secret="secret-rollback",
    )
    host = await bind_real_runtime(
        rt, monkeypatch, reply="isolated actual answer"
    )
    old_pid = await ready(rt)
    old_identity = identity(rt)
    sessions = await exchange(
        rt,
        host,
        accounts,
        "account-rollback",
        "before-update",
        "before update",
    )
    assert sessions
    original = {
        p.relative_to(rt.source): p.read_bytes()
        for p in rt.source.rglob("*")
        if p.is_file()
    }
    config = dict(rt.channel._launch_spec.config)
    candidate = official_qq_zip(tmp_path / "candidate", "qq")
    manifest_path = candidate / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "99.0.0"
    manifest_path.write_text(json.dumps(manifest))
    witness = tmp_path / "candidate-connected-pid"
    # Only this controlled candidate differs. Authentic native Platform/start,
    # socket READY, HTTP client and real Loader cleanup execute before failure.
    with (candidate / "qwenpaw_channel_qq/driver.py").open("a") as f:
        f.write(
            "\nimport asyncio as _test_asyncio\n"
            "import os as _test_os\n"
            "from pathlib import Path as _TestPath\n"
            "_RealQQDriver = QQDriver\n"
            "class QQDriver(_RealQQDriver):\n"
            "    async def start(self, config):\n"
            "        self._candidate_ready = _test_asyncio.Event()\n"
            "        await super().start(config)\n"
            "        await self._candidate_ready.wait()\n"
            f"        witness = _TestPath({str(witness)!r})\n"
            "        witness.write_text(str(_test_os.getpid()))\n"
            "        raise RuntimeError('CONTROLLED_AFTER_NATIVE_READY')\n"
            "    async def _state_changed(self, state):\n"
            "        if state == 'connected':\n"
            "            self._candidate_ready.set()\n"
            "            return\n"
            "        await super()._state_changed(state)\n"
        )
    before_connections = len(accounts.connections)
    report = await rt.loader.lifecycle.reload("qq", new_source=candidate)
    assert not report.ok and report.errors
    assert witness.exists()
    candidate_pid = int(witness.read_text())
    assert candidate_pid != old_pid and not psutil.pid_exists(candidate_pid)
    assert len(accounts.connections) == before_connections + 2
    candidate_socket = accounts.connections[before_connections]
    assert candidate_socket.close_code is not None
    assert {
        p.relative_to(rt.source): p.read_bytes()
        for p in rt.source.rglob("*")
        if p.is_file()
    } == original
    assert {p: p.read_bytes() for p in sessions} == sessions
    pid = await ready(rt)
    assert pid != old_pid and not psutil.pid_exists(old_pid)
    assert identity(rt)["generation"] > old_identity["generation"]
    assert dict(rt.channel._launch_spec.config) == config
    await exchange(
        rt,
        host,
        accounts,
        "account-rollback",
        "after-rollback",
        "after rollback",
    )
    assert len(host.builds) == len(rt.ws.requests) == 2
    assert all(
        "before update" in p.read_text() and "after rollback" in p.read_text()
        for p in sessions
    )
    receipt = await rt.manager.stop_one("qq")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not psutil.pid_exists(pid)
    assert not rt.loader.registry.runtime_owners.leases("qq")
