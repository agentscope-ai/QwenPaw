"""Native QR authority commits one workspace before its real runtime starts."""

import asyncio
from importlib import import_module
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import psutil
import pytest
import pytest_asyncio

from extension_process_suite import eventually
from real_host_runtime import bind_real_runtime
from wechat_w4_formal_support import (
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)
from wechat_w4_waiting_support import native_ilink, qr_ilink

__all__ = ["runtime", "native_ilink", "qr_ilink", "wechat_host_import_guard"]


def prepare_profiles(rt, external, tmp_path):
    from qwenpaw.config.config import (
        AgentProfileConfig,
        AgentProfileRef,
        ChannelConfig,
        load_agent_config,
        save_agent_config,
    )
    from qwenpaw.config.utils import load_config, save_config

    bdir = tmp_path / "workspace-B"
    bdir.mkdir()
    root = load_config()
    root.agents.profiles["B"] = AgentProfileRef(
        id="B", workspace_dir=str(bdir)
    )
    save_config(root)
    a = load_agent_config("A")
    a.channels = ChannelConfig.model_validate(
        {
            "wechat": {
                "enabled": False,
                "base_url": external.mock.base_url,
                "bot_token_file": "qr-auth/token",
                "media_dir": "qr-media",
                "no_text_debounce": True,
            }
        }
    )
    save_agent_config("A", a)
    b = AgentProfileConfig(
        id="B",
        name="B",
        workspace_dir=str(bdir),
        channels={
            "wechat": {"enabled": False, "media_dir": str(bdir / "media")}
        },
    )
    save_agent_config("B", b)
    return a, b


@pytest_asyncio.fixture
async def qr_saved_runtime(runtime, qr_ilink, monkeypatch, tmp_path):
    from qwenpaw.app.channels.management import ChannelManagementService
    from qwenpaw.app.channels.manager import ChannelManager
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.app.channels.qrcode_sessions import ChannelQRCodeSessions
    from qwenpaw.app.multi_agent_manager import MultiAgentManager

    cwd = tmp_path / "host-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    rt = await runtime(
        "wechat",
        workspace_name="A",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "warm/token"),
        base_url=qr_ilink.mock.base_url,
    )
    host = await bind_real_runtime(
        rt, monkeypatch, reply="authorized QR reply"
    )
    assert (await rt.manager.stop_one("wechat")).stopped
    a, b = prepare_profiles(rt, qr_ilink, tmp_path)
    auth = cwd / "qr-auth/token"
    auth.parent.mkdir()
    auth.write_text("untouched-old-file-token")
    context = auth.parent / "wechat_context_tokens.json"
    context.write_text(json.dumps({"old-user": "retained-context"}))
    (cwd / "qr-media").mkdir()
    service = ChannelManagementService(rt.loader)
    sessions = ChannelQRCodeSessions(rt.loader, service)
    mam = MultiAgentManager()
    mam.channel_qrcode_sessions = sessions
    app = FastAPI()
    app.include_router(import_module("qwenpaw.app.routers.config").router)
    app.state.plugin_loader = rt.loader
    app.state.channel_management = service
    app.state.channel_qrcode_sessions = sessions
    app.state.multi_agent_manager = mam
    bmanager = ChannelManager.from_config(
        rt.ws.stream_query,
        b,
        workspace_dir=Path(b.workspace_dir),
    )
    await bmanager.start_all()
    management_pids = []
    original = ChannelProcess.start_management

    async def observe_actual_start(process, spec):
        result = await original(process, spec)
        management_pids.append(process.health_snapshot()["pid"])
        return result

    monkeypatch.setattr(
        ChannelProcess, "start_management", observe_actual_start
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield SimpleNamespace(
                rt=rt,
                host=host,
                a=a,
                b=b,
                mam=mam,
                sessions=sessions,
                client=client,
                external=qr_ilink,
                auth=auth,
                context=context,
                cwd=cwd,
                bmanager=bmanager,
                management_pids=management_pids,
            )
    finally:
        await sessions.aclose()
        await service.aclose()
        await bmanager.stop_all()
        await asyncio.sleep(0)


def profile_bytes(state):
    return {
        name: (Path(profile.workspace_dir) / "agent.json").read_bytes()
        for name, profile in (("A", state.a), ("B", state.b))
    }


async def authorize_native_http_save(state):
    from qwenpaw.config.config import load_agent_config

    headers = {"X-Agent-Id": "A"}
    fetched = await state.client.get(
        "/config/channels/wechat/qrcode", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    token = fetched.json()["poll_token"]
    state.external.qr_confirmed = True
    polled = await state.client.get(
        "/config/channels/wechat/qrcode/status",
        params={"token": token},
        headers=headers,
    )
    assert polled.status_code == 200, polled.text
    result = polled.json()
    assert result["status"] == "confirmed"
    assert result["credentials"] == {
        "bot_token": "temporary-file-token",
        "base_url": state.external.mock.base_url,
    }
    assert len(state.management_pids) == 2
    assert all(
        pid != os.getpid() and not psutil.pid_exists(pid)
        for pid in state.management_pids
    )
    values = {
        **state.a.channels.wechat.model_dump(mode="json"),
        **result["credentials"],
        "enabled": True,
    }
    before = profile_bytes(state)
    denied = await state.client.put(
        "/config/channels/wechat",
        json=values,
        headers={"X-Agent-Id": "B", "X-Channel-Auth-Session": token},
    )
    assert denied.status_code == 403
    assert profile_bytes(state) == before
    response = await state.client.put(
        "/config/channels/wechat",
        json=values,
        headers={**headers, "X-Channel-Auth-Session": token},
    )
    assert response.status_code == 200, response.text
    saved = load_agent_config("A")
    assert saved.channels.wechat.model_dump(mode="json") == values
    assert response.json() == values
    assert profile_bytes(state)["B"] == before["B"]
    assert state.auth.read_text() == "untouched-old-file-token"
    assert json.loads(state.context.read_text()) == {
        "old-user": "retained-context"
    }
    assert not state.rt.loader.registry.runtime_owners.leases("wechat")
    await asyncio.sleep(0)
    assert state.mam._config_generations == {"A": 1}
    assert not state.mam.agents
    return saved


async def reject_b_same_slot(state, saved):
    from qwenpaw.app.channels.management import ManagementError

    candidate = state.b.model_copy(deep=True)
    candidate.channels.wechat = saved.channels.wechat.model_copy(deep=True)
    before = state.rt.loader.registry.runtime_owners.leases("wechat")
    with pytest.raises(ManagementError) as caught:
        await state.bmanager.start_one("wechat", candidate)
    assert caught.value.reason_code == "ACCOUNT_IN_USE"
    assert state.rt.loader.registry.runtime_owners.leases("wechat") == before
    assert await state.bmanager.get_channel("wechat") is None


@pytest.mark.asyncio
async def test_native_qr_authorized_put_starts_saved_runtime_and_fences_b(
    qr_saved_runtime,
    tmp_path,
):
    state = qr_saved_runtime
    saved = await authorize_native_http_save(state)
    state.rt.ws._config = saved
    state.rt.ws.config = saved
    await state.rt.manager.start_one("wechat", saved)
    channel = await state.rt.manager.get_channel("wechat")
    pid = channel.channel_process.health_snapshot()["pid"]
    assert (
        channel.channel_process.health_snapshot()["platform_state"]
        == "connected"
    )
    config = channel._launch_spec.config
    assert config["bot_token"] == saved.channels.wechat.bot_token
    assert config["bot_token_file"] == str(state.auth)
    assert config["media_dir"] == str(state.cwd / "qr-media")
    assert channel._launch_spec.workspace_id == str(
        Path(saved.workspace_dir).resolve()
    )
    await reject_b_same_slot(state, saved)
    state.external.mock.push_text_message(
        text="inbound after authorized save",
        from_user_id="saved-user@im.wechat",
        context_token="saved-runtime-context",
    )
    await eventually(lambda: len(state.external.mock.sent_messages) == 1)
    sent = state.external.mock.sent_messages[0]
    assert sent["to_user_id"] == "saved-user@im.wechat"
    assert sent["context_token"] == "saved-runtime-context"
    assert sent["item_list"] == [
        {"type": 1, "text_item": {"text": "authorized QR reply"}}
    ]
    assert len(state.host.calls) == len(state.host.builds) == 1
    assert state.host.builds[0]["agent"] == "QwenPawAgent"
    assert all(row["authenticated"] for row in state.external.requests)
    assert state.auth.read_text() == "untouched-old-file-token"
    assert json.loads(state.context.read_text()) == {
        "old-user": "retained-context",
        "saved-user@im.wechat": "saved-runtime-context",
    }
    persisted = profile_bytes(state)
    owners = state.rt.loader.registry.runtime_owners
    assert (
        sum(
            lease.key.kind == "wechat_auth"
            for lease in owners.leases("wechat")
        )
        == 3
    )
    receipt = await state.rt.manager.stop_one("wechat")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == () and not psutil.pid_exists(pid)
    assert owners.leases("wechat") == ()
    await reject_b_same_slot(state, saved)
    assert profile_bytes(state) == persisted
    (tmp_path / "qr-save-runtime-observation.json").write_text(
        json.dumps(
            {
                "management_worker_pids": state.management_pids,
                "actual_agent_builds": state.host.builds,
                "wrong_scope_put_status": 403,
                "authorized_put_status": 200,
                "unloaded_manager_generations": state.mam._config_generations,
                "explicit_saved_config_manager_start": True,
                "native_send_count": len(state.external.mock.sent_messages),
                "b_rejected_while_running_and_after_stop": True,
                "persisted_config_unchanged_by_stop": profile_bytes(state)
                == persisted,
                "stop_receipt": {
                    "stopped": receipt.stopped,
                    "exited": receipt.exited,
                    "forced": receipt.forced,
                    "residual": list(receipt.residual),
                },
                "remaining_wechat_leases": len(owners.leases("wechat")),
            },
            indent=2,
        )
    )
