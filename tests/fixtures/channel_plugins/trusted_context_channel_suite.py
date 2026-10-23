"""Actual channel run/manage and SIP config projection before catalog cutover."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, distribution
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.process_supervisor import ChannelProcess
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.plugins.channel_adapter import ChannelDescription
from qwenpaw.plugins.execution.bootstrap import _hash_code_root
from qwenpaw.plugins.official_execution_context import (
    project_official_execution,
)
from sip_artifact_suite import CONFIG_DEFAULTS

ROOT = Path(__file__).resolve().parents[3]


async def until(check):
    async with asyncio.timeout(5):
        while not check():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", ["", "explicit-config-key"])
async def test_normal_sip_factory_projects_host_key_into_real_child_asr(
    tmp_path, monkeypatch, explicit
):
    from qwenpaw.config.config import Config

    monkeypatch.setattr("qwenpaw.app.channels.base.load_config", Config)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "actual-host-env-key")
    code, work, site = (
        tmp_path / name for name in ("code", "work", "vendor-site")
    )
    work.mkdir()
    site.mkdir()
    shutil.copytree(
        ROOT / "plugins/channel/sip",
        code,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    ns = code / "qwenpaw_channel_sip"
    fixtures = Path(__file__).parent
    (ns / "vendor_boundary.py").write_bytes(
        (fixtures / "sip_vendor_boundary.py").read_bytes()
    )
    (ns / "test_boundary.py").write_text(
        "WORK = "
        + repr(str(work))
        + "\n"
        + (fixtures / "sip_process_boundary.py").read_text()
    )
    descriptor = json.loads((code / "channel.json").read_text())
    descriptor["entrypoint"]["module"] = "qwenpaw_channel_sip.test_boundary"
    (code / "channel.json").write_text(json.dumps(descriptor))
    for name, version in [
        ("pyVoIP", "1.6.0"),
        ("dashscope-realtime", "0.1.0"),
    ]:
        # Keep real installed metadata; duplicate test dist-info is ambiguous.
        try:
            distribution(name)
        except PackageNotFoundError:
            pass
        else:
            continue
        metadata = site / (
            name.replace("-", "_") + "-" + version + ".dist-info"
        )
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        )
    raw = {
        **CONFIG_DEFAULTS,
        "enabled": True,
        "sip_server": "registrar.test",
        "sip_port": 25063,
        "dashscope_api_key": explicit,
        "welcome_greeting": "",
        "private_env": {"DASHSCOPE_API_KEY": "untrusted-client-key"},
    }
    saved = deepcopy(raw)
    projected, env = project_official_execution(
        "sip",
        raw,
        working_dir=tmp_path,
        legacy_state_dir=tmp_path / "legacy",
        environment=os.environ,
        workspace_dir=work,
    )
    assert env == {}
    description = ChannelDescription(
        "sip",
        "2.0.0",
        SharedChannelDescriptor.load(code / "channel.json"),
        code / "channel.json",
        code,
        code / "requirements.txt",
        (),
        _hash_code_root(code),
        "SIP",
        "Private precutover policy exercise",
    )

    async def no_agent(request):
        raise AssertionError("ASR key observation is not Agent execution")
        yield

    channel = description.create_proxy(
        no_agent,
        projected,
        private_env=env,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="sip-context",
        generation=1,
        qwenpaw_version="2.2.2b4",
        dependency_paths=(site,),
        workspace_dir=work,
    )
    assert channel._launch_spec.private_env == {}
    assert "private_env" not in channel._launch_spec.config
    assert raw == saved

    def rows():
        path = work / "ledger.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    try:
        await channel.start()
        with (work / "inbox.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "kind": "incoming",
                        "call_id": "real-key-call",
                        "sender": "sip:caller@example.test",
                    }
                )
                + "\n"
            )
        await until(lambda: any(row["kind"] == "asr" for row in rows()))
        row = next(row for row in rows() if row["kind"] == "asr")
        assert row["key"] == (explicit or "actual-host-env-key")
        assert (
            row["pid"]
            == channel.channel_process.health_snapshot()["pid"]
            != os.getpid()
        )
        assert raw == saved
    finally:
        (work / "stop-boundary").touch()
        receipt = await channel.stop()
        assert receipt.exited and not receipt.residual


@pytest.mark.asyncio
async def test_actual_channel_runtime_and_static_manage_share_private_environment(
    tmp_path,
):
    from management_process_suite import (
        management_sample_source,
        management_spec,
        management_request,
    )

    sample = management_sample_source(tmp_path, run_driver=True)
    ledger = tmp_path / "context-ledger.jsonl"
    (sample.source / "management_sample/driver.py").write_text(
        "LEDGER = "
        + repr(str(ledger))
        + "\n"
        + """import json,os
from pathlib import Path
def observe(stage):
    with Path(LEDGER).open('a') as out:
        out.write(json.dumps({'stage':stage,'pid':os.getpid(),'env':{k:os.environ.get(k) for k in ('QQ_API_BASE','QQ_TOKEN_URL','QQ_PORTAL_HOST','UNRELATED_HOST_SECRET')}})+'\\n')
class Driver:
    def bind(self,context): self.context=context
    async def start(self,config):
        observe('run')
        await self.context.set_platform_state('connected')
    async def stop(self): pass
    @staticmethod
    async def manage(request):
        observe('manage')
        data=request.to_mapping()
        fields=('request_id','plugin_id','workspace_id','channel_key','instance_id','generation','source_revision','operation')
        return {**{key:data[key] for key in fields},'outcome':'ok','reason_code':None,'result':{'scan_url':'https://example.invalid/scan','continuation':'test-continuation'}}
"""
    )
    expected = {
        "QQ_API_BASE": "http://127.0.0.1:19001",
        "QQ_TOKEN_URL": "http://127.0.0.1:19002",
        "QQ_PORTAL_HOST": "127.0.0.1:19003",
    }
    _, env = project_official_execution(
        "qq",
        {},
        working_dir=tmp_path,
        legacy_state_dir=tmp_path / "legacy",
        environment={**expected, "UNRELATED_HOST_SECRET": "not-for-child"},
    )
    spec = replace(management_spec(sample), private_env=env)
    run, manage = ChannelProcess(), ChannelProcess()
    try:
        await run.start(replace(spec, enabled=True))
        await until(
            lambda: run.health_snapshot()["platform_state"] == "connected"
        )
        stopped = await run.stop()
        assert stopped.exited and not stopped.residual
        await manage.start_management(spec)
        request = management_request(
            spec, SimpleNamespace(host="127.0.0.1", port=9)
        )
        result = await manage.call(
            "channel.management.execute", request.to_mapping()
        )
        assert result["outcome"] == "ok"
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        assert [row["stage"] for row in rows] == ["run", "manage"]
        assert all(
            row["env"] == {**expected, "UNRELATED_HOST_SECRET": None}
            for row in rows
        )
        assert rows[0]["pid"] != rows[1]["pid"] and all(
            row["pid"] != os.getpid() for row in rows
        )
    finally:
        for process in (run, manage):
            result = await process.stop()
            assert result.exited and not result.residual


@pytest.mark.asyncio
async def test_third_party_factory_cannot_claim_official_host_environment(
    tmp_path, monkeypatch
):
    from qwenpaw.config.config import Config

    monkeypatch.setattr("qwenpaw.app.channels.base.load_config", Config)
    monkeypatch.setenv("QQ_API_BASE", "https://host-only.example.invalid")
    monkeypatch.setenv("QQ_TOKEN_URL", "https://host-token.example.invalid")
    monkeypatch.setenv("QQ_PORTAL_HOST", "host-portal.example.invalid")
    code = tmp_path / "code"
    code.mkdir()
    ledger = tmp_path / "observation.json"
    (code / "observer.py").write_text(
        "LEDGER = "
        + repr(str(ledger))
        + "\n"
        + """import json,os
from pathlib import Path
class Driver:
    def bind(self,context): self.context=context
    async def start(self,config):
        Path(LEDGER).write_text(json.dumps({'env':{k:os.environ.get(k) for k in ('QQ_API_BASE','QQ_TOKEN_URL','QQ_PORTAL_HOST')},'config_has_private_env':'private_env' in config,'pid':os.getpid()}))
        await self.context.set_platform_state('connected')
    async def stop(self): pass
"""
    )
    descriptor = json.loads(
        (ROOT / "plugins/channel/qq/channel.json").read_text()
    )
    descriptor["entrypoint"]["module"] = "observer"
    descriptor["entrypoint"]["qualname"] = "Driver"
    (code / "channel.json").write_text(json.dumps(descriptor))
    (code / "requirements.txt").write_text("")
    description = ChannelDescription(
        "fixture.thirdparty",
        "1.0.0",
        SharedChannelDescriptor.load(code / "channel.json"),
        code / "channel.json",
        code,
        code / "requirements.txt",
        (),
        _hash_code_root(code),
        "Third party",
        "No official authority",
    )

    async def no_agent(request):
        raise AssertionError("No Agent expected")
        yield

    raw = {
        "enabled": True,
        "private_env": {
            "QQ_API_BASE": "https://client-injection.example.invalid"
        },
    }
    saved = deepcopy(raw)
    channel = description.create_proxy(
        no_agent,
        raw,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="untrusted-context",
        generation=1,
        qwenpaw_version="2.2.2b4",
        workspace_dir=tmp_path / "work",
    )
    try:
        await channel.start()
        result = json.loads(ledger.read_text())
        assert result["env"] == {
            "QQ_API_BASE": None,
            "QQ_TOKEN_URL": None,
            "QQ_PORTAL_HOST": None,
        }
        assert not result["config_has_private_env"]
        assert (
            result["pid"]
            == channel.channel_process.health_snapshot()["pid"]
            != os.getpid()
        )
        assert raw == saved and channel._launch_spec.private_env == {}
    finally:
        result = await channel.stop()
        assert result.exited and not result.residual
