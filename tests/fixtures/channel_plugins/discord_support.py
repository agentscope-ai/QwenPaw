"""Small Discord SDK boundary and real worker helpers."""

import importlib.metadata
import json
import uuid
from pathlib import Path
import shutil
from types import SimpleNamespace as NS

from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest

from extension_process_suite import eventually, identity, runtime
from extension_sample import ROOT
from g2_fault_runtime import fault_runtime
from g2_lifecycle_suite import copied_sdk
from g2_official_process_suite import official_source


def rows(work, kind=None, *, token="local-A"):
    path = Path(work) / token / "ledger.jsonl"
    values = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return [row for row in values if kind is None or row["kind"] == kind]


def push(work, ident=1, *, token="local-A", **data):
    target = Path(work) / token
    target.mkdir(parents=True, exist_ok=True)
    with (target / "inbox.jsonl").open("a") as stream:
        stream.write(json.dumps({"id": ident, **data}) + "\n")


def set_mode(work, mode, *, token="local-A"):
    target = Path(work) / token
    target.mkdir(parents=True, exist_ok=True)
    (target / "mode").write_text(mode)


@pytest.fixture
def discord_sdk(tmp_path, fault_runtime):
    work, site = tmp_path / "network", tmp_path / "sdk"
    work.mkdir()
    site.mkdir()
    pending, copied = ["discord.py"], set(fault_runtime.packages)
    environment = {**default_environment(), "extra": ""}
    while pending:
        distribution = importlib.metadata.distribution(pending.pop())
        name = distribution.metadata["Name"].lower().replace("_", "-")
        if name in copied:
            continue
        copied.add(name)
        for requirement in distribution.requires or ():
            dependency = Requirement(requirement)
            if dependency.marker is None or dependency.marker.evaluate(
                environment
            ):
                pending.append(dependency.name)
        for relative in distribution.files or ():
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "__pycache__" in relative.parts
            ):
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = site / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    boundary = Path(__file__).with_name("discord_process_boundary.py")
    copied_sdk(
        tmp_path,
        "discord.py",
        "discord",
        "discord/__init__.py",
        "\nWORK = " + repr(str(work)) + "\n" + boundary.read_text(),
        site=site,
    )
    return NS(
        work=work,
        site=site,
        python=fault_runtime.python,
        identity=fault_runtime.identity,
    )


async def discord(runtime, sdk, *, token="local-A", **settings):
    rt = await runtime(
        "discord",
        source_factory=official_source,
        python_executable=sdk.python,
        runtime_identity=sdk.identity,
        dependency_paths=(sdk.site,),
        bot_token=token,
        **settings,
    )
    await eventually(lambda: bool(rows(sdk.work, "gateway", token=token)))
    return rt


async def route(rt, target="discord:ch:123", meta=None):
    result = await rt.process.call(
        "channel.response.open",
        {
            **identity(rt),
            "to_handle": target,
            "meta": meta or {},
        },
    )
    return result["response_handle"]


async def finish(rt, handle, outcome="completed"):
    return await rt.process.call(
        "channel.response.finish",
        {
            **identity(rt),
            "response_handle": handle,
            "outcome": outcome,
        },
    )


async def send(
    rt,
    handle,
    *,
    parts=None,
    delivery_id=None,
    operation="message.create",
    **fields,
):
    return await rt.process.call(
        "channel.send",
        {
            **identity(rt),
            "delivery_id": delivery_id or uuid.uuid4().hex,
            "to_handle": handle,
            "operation": operation,
            **({"content_parts": parts} if parts is not None else {}),
            **fields,
        },
    )


async def callback_done(sdk, count=1, *, token="local-A"):
    await eventually(
        lambda: len(rows(sdk.work, "callback-end", token=token)) >= count + 1
    )
