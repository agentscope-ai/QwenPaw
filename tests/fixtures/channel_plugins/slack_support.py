"""Slack external boundary plus existing real Loader/worker helpers."""

import importlib.metadata
import base64
import csv
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace as NS

from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest

from extension_process_suite import eventually, identity, runtime
from g2_fault_runtime import fault_runtime
from g2_lifecycle_suite import copied_sdk, residual_child_code
from g2_official_process_suite import official_source
from discord_support import route, finish, send


def rows(work, kind=None, *, token="local-A"):
    path = Path(work) / token / "ledger.jsonl"
    values = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return [row for row in values if kind is None or row["kind"] == kind]


def set_mode(work, value, *, token="local-A"):
    path = Path(work) / token
    path.mkdir(parents=True, exist_ok=True)
    (path / "mode").write_text(value)


def push(work, ident=1, *, token="local-A", callback="message", **fields):
    path = Path(work) / token
    path.mkdir(parents=True, exist_ok=True)
    event = {
        "type": callback,
        "channel": "D123",
        "user": "U456",
        "ts": f"1000000000.{ident:06d}",
        "text": "Hello bot",
        **fields,
    }
    payload = {
        "type": "event_callback",
        "team_id": "T999",
        "api_app_id": "A999",
        "event_id": "Ev" + str(ident),
        "event_time": 1000000000,
        "event": event,
    }
    if callback == "slash_commands":
        payload = {
            "team_id": "T999",
            "channel_id": "C123",
            "user_id": "U456",
            "user_name": "Human",
            "command": "/help",
            "text": "details",
            "response_url": "https://hooks.slack.com/commands/local",
            "trigger_id": str(ident),
            **fields,
        }
    envelope = {
        "type": (
            "slash_commands" if callback == "slash_commands" else "events_api"
        ),
        "envelope_id": "envelope-" + str(ident),
        "accepts_response_payload": callback == "slash_commands",
        "payload": payload,
    }
    with (path / "inbox.jsonl").open("a") as stream:
        stream.write(json.dumps(envelope) + "\n")


@pytest.fixture
def slack_sdk(tmp_path, fault_runtime):
    work, site = tmp_path / "network", tmp_path / "slack-sdk"
    work.mkdir()
    site.mkdir()
    pending, copied = ["slack-bolt", "slack-sdk", "aiohttp", "aiofiles"], set(
        fault_runtime.packages
    )
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
    shutil.copy2(
        Path(__file__).with_name("slack_process_boundary.py"),
        site / "qwenpaw_slack_test_boundary.py",
    )
    with (site / "qwenpaw_slack_test_boundary.py").open("a") as stream:
        stream.write(residual_child_code(tmp_path, True))
    (site / "slack-test-work").write_text(str(work))
    copied_sdk(
        tmp_path,
        "slack-sdk",
        "slack_sdk",
        "slack_sdk/web/async_client.py",
        (
            "\nfrom qwenpaw_slack_test_boundary import install_w"
            "eb\ninstall_web(AsyncWebClient)\n"
        ),
        site=site,
    )
    copied_sdk(
        tmp_path,
        "slack-sdk",
        "slack_sdk/socket_mode/aiohttp",
        "slack_sdk/socket_mode/aiohttp/__init__.py",
        (
            "\nfrom qwenpaw_slack_test_boundary import install_s"
            "ocket\ninstall_socket(SocketModeClient)\n"
        ),
        site=site,
    )
    record = next(site.glob("slack_sdk-*.dist-info/RECORD"))
    with record.open(newline="") as stream:
        metadata = list(csv.reader(stream))
    for row in metadata:
        if row[0] in {
            "slack_sdk/web/async_client.py",
            "slack_sdk/socket_mode/aiohttp/__init__.py",
        }:
            data = (site / row[0]).read_bytes()
            row[1:] = [
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                .decode()
                .rstrip("="),
                str(len(data)),
            ]
    with record.open("w", newline="") as stream:
        csv.writer(stream).writerows(metadata)
    return NS(
        work=work,
        site=site,
        python=fault_runtime.python,
        identity=fault_runtime.identity,
    )


async def slack(runtime, sdk, *, token="local-A", **settings):
    return await runtime(
        "slack",
        source_factory=official_source,
        python_executable=sdk.python,
        runtime_identity=sdk.identity,
        dependency_paths=(sdk.site,),
        bot_token=token,
        app_token="xapp-test-token",
        **settings,
    )


async def callback_done(sdk, count=1, *, token="local-A"):
    await eventually(
        lambda: len(rows(sdk.work, "platform-ack", token=token)) >= count
    )
