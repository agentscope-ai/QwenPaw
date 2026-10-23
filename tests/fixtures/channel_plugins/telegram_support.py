"""Telegram service fixture on the shared G2 worker interpreter."""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace as NS
from urllib.parse import quote

import pytest

from extension_process_suite import eventually, identity, runtime
from g2_fault_runtime import fault_runtime
from g2_lifecycle_suite import copied_sdk
from g2_official_process_suite import official_source
from discord_support import route, finish, send

TOKEN = "123:local-A"


def rows(work, kind=None, *, token=TOKEN):
    path = Path(work) / quote(token, safe="") / "ledger.jsonl"
    values = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return [v for v in values if kind is None or v["kind"] == kind]


def set_mode(work, value, *, token=TOKEN):
    path = Path(work) / quote(token, safe="")
    path.mkdir(parents=True, exist_ok=True)
    (path / "mode").write_text(value)


def push(work, ident=1, *, token=TOKEN, callback="message", **fields):
    path = Path(work) / quote(token, safe="")
    path.mkdir(parents=True, exist_ok=True)
    event = {
        "message_id": ident,
        "date": 1000000000,
        "chat": {"id": 12345, "type": "private"},
        "from": {
            "id": 456,
            "is_bot": False,
            "first_name": "Human",
            "username": "human",
        },
        "text": "Hello bot",
        **fields,
    }
    if callback == "callback_query":
        event = {
            "id": "query-" + str(ident),
            "chat_instance": "local-chat",
            "from": event["from"],
            "data": "tga:pending-A",
            "message": event,
            **fields,
        }
    value = {"update_id": ident, callback: event}
    with (path / "inbox.jsonl").open("a") as output:
        output.write(json.dumps(value) + "\n")
    return value


@pytest.fixture
def telegram_sdk(tmp_path, fault_runtime):
    work, site = tmp_path / "network", fault_runtime.site
    work.mkdir()
    site.mkdir(exist_ok=True)
    copied_sdk(
        tmp_path,
        "python-telegram-bot",
        "telegram",
        "telegram/__init__.py",
        "",
        site=site,
    )
    shutil.copy2(
        Path(__file__).with_name("telegram_process_boundary.py"),
        site / "qwenpaw_telegram_test_boundary.py",
    )
    (site / "telegram-test-work").write_text(str(work))
    copied_sdk(
        tmp_path,
        "httpx",
        "httpx",
        "httpx/__init__.py",
        "\nfrom qwenpaw_telegram_test_boundary import install\ninstall()\n",
        site=site,
    )
    return NS(
        work=work,
        site=site,
        python=fault_runtime.python,
        identity=fault_runtime.identity,
    )


async def telegram(runtime, sdk, *, token=TOKEN, **settings):
    rt = await runtime(
        "telegram",
        source_factory=official_source,
        python_executable=sdk.python,
        runtime_identity=sdk.identity,
        dependency_paths=(sdk.site,),
        bot_token=token,
        **settings,
    )
    await eventually(lambda: bool(rows(sdk.work, "getUpdates", token=token)))
    return rt


async def bind_telegram_runtime(rt, monkeypatch):
    """Complete the normal command registry after the shared Agent binding."""
    from real_host_runtime import bind_real_runtime
    from qwenpaw.runtime.builtin_commands import collect_builtin_command_specs

    host = await bind_real_runtime(rt, monkeypatch)
    for spec in collect_builtin_command_specs():
        rt.ws.plugins.slash_command_registry.register(spec)
    return host
