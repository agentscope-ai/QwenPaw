# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DataPaw send_file_to_user wrapping."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote


REPORT_REL = "1778472702210/graph_ATp6bnvQ/generate_report/report.html"
CSS_REL = "1778472702210/graph_ATp6bnvQ/generate_report/assets/report.css"
CSV_REL = "1778472702210/graph_ATp6bnvQ/data/result.csv"

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="./assets/report.css">
  <style>.hero { background: url('../images/hero.png'); }</style>
</head>
<body>
  <a href="../data/result.csv">csv</a>
  <img srcset="./small.png 1x, ./large.png 2x">
</body>
</html>
""".strip()


class _FakeToolkit:
    def __init__(self, include_send: bool = True):
        self.tools = {"send_file_to_user": object()} if include_send else {}
        self.registered = []

    def register_tool_function(self, fn, namesake_strategy="skip"):
        self.registered.append((fn.__name__, namesake_strategy))
        self.tools[fn.__name__] = fn


def _agent(tmp_path, *, request_context=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return SimpleNamespace(
        _agent_config=SimpleNamespace(id="datapaw"),
        _workspace_dir=workspace,
        _request_context=request_context
        if request_context is not None
        else {
            "session_id": "s1",
            "user_id": "default",
            "agent_id": "datapaw",
            "api_origin": "http://testserver",
        },
    )


def _write_artifact_report(tmp_path) -> Path:
    report_path = tmp_path / "workspace" / "artifacts" / REPORT_REL
    report_path.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / "artifacts" / CSS_REL).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    (tmp_path / "workspace" / "artifacts" / CSV_REL).parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path.write_text(SAMPLE_HTML, encoding="utf-8")
    return report_path


def test_register_file_delivery_overrides_existing_host_tool() -> None:
    from plugin_datapaw.core.agents.base import DataPawAgent

    agent = DataPawAgent.__new__(DataPawAgent)
    agent.toolkit = _FakeToolkit(include_send=True)

    agent._register_file_delivery_tool()

    assert ("send_file_to_user", "override") in agent.toolkit.registered
    assert callable(agent.toolkit.tools["send_file_to_user"])


def test_register_file_delivery_respects_disabled_host_tool() -> None:
    from plugin_datapaw.core.agents.base import DataPawAgent

    agent = DataPawAgent.__new__(DataPawAgent)
    agent.toolkit = _FakeToolkit(include_send=False)

    agent._register_file_delivery_tool()

    assert agent.toolkit.registered == []
    assert "send_file_to_user" not in agent.toolkit.tools


def test_html_artifact_send_generates_rewritten_copy(tmp_path) -> None:
    from plugin_datapaw.core.file_delivery import build_send_file_to_user_fn

    report_path = _write_artifact_report(tmp_path)
    sent_paths: list[str] = []

    async def fake_host_send(file_path: str):
        sent_paths.append(file_path)
        return {"sent": file_path}

    tool = build_send_file_to_user_fn(_agent(tmp_path))
    with patch(
        "plugin_datapaw.core.file_delivery._host_send_file_to_user",
        new=fake_host_send,
    ):
        asyncio.run(tool(f"artifacts/{REPORT_REL}"))
        asyncio.run(tool(f"artifacts/{REPORT_REL}"))

    copy_path = report_path.with_name("report.datapaw-send.html")
    assert sent_paths == [str(copy_path), str(copy_path)]
    assert copy_path.is_file()
    assert list(report_path.parent.glob("report.datapaw-send*.html")) == [
        copy_path,
    ]
    assert report_path.read_text(encoding="utf-8") == SAMPLE_HTML

    body = copy_path.read_text(encoding="utf-8")
    csv_url = (
        "http://testserver/api/tasks/s1/files/resource"
        f"?path={quote(CSV_REL, safe='')}"
        "&amp;user_id=default&amp;agent_id=datapaw"
    )
    css_url = (
        "http://testserver/api/tasks/s1/files/resource"
        f"?path={quote(CSS_REL, safe='')}"
        "&amp;user_id=default&amp;agent_id=datapaw"
    )
    assert csv_url in body
    assert css_url in body
    assert "href=\"../data/result.csv\"" not in body


def test_html_artifact_send_rewrites_absolute_artifact_links(tmp_path) -> None:
    from plugin_datapaw.core.file_delivery import build_send_file_to_user_fn

    report_path = _write_artifact_report(tmp_path)
    artifacts_root = tmp_path / "workspace" / "artifacts"
    absolute_csv = (artifacts_root / CSV_REL).resolve()
    report_path.write_text(
        (
            f'<a href="{absolute_csv.as_posix()}">csv</a>'
            f'<a href="{absolute_csv.as_uri()}">csv-file</a>'
        ),
        encoding="utf-8",
    )
    sent_paths: list[str] = []

    async def fake_host_send(file_path: str):
        sent_paths.append(file_path)
        return {"sent": file_path}

    tool = build_send_file_to_user_fn(_agent(tmp_path))
    with patch(
        "plugin_datapaw.core.file_delivery._host_send_file_to_user",
        new=fake_host_send,
    ):
        asyncio.run(tool(f"artifacts/{REPORT_REL}"))

    copy_path = report_path.with_name("report.datapaw-send.html")
    assert sent_paths == [str(copy_path)]
    body = copy_path.read_text(encoding="utf-8")
    csv_url = (
        "http://testserver/api/tasks/s1/files/resource"
        f"?path={quote(CSV_REL, safe='')}"
        "&amp;user_id=default&amp;agent_id=datapaw"
    )
    assert csv_url in body
    assert absolute_csv.as_posix() not in body
    assert absolute_csv.as_uri() not in body


def test_non_html_send_passthrough(tmp_path) -> None:
    from plugin_datapaw.core.file_delivery import build_send_file_to_user_fn

    csv_path = tmp_path / "workspace" / "artifacts" / CSV_REL
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    sent_paths: list[str] = []

    async def fake_host_send(file_path: str):
        sent_paths.append(file_path)
        return {"sent": file_path}

    tool = build_send_file_to_user_fn(_agent(tmp_path))
    with patch(
        "plugin_datapaw.core.file_delivery._host_send_file_to_user",
        new=fake_host_send,
    ):
        asyncio.run(tool(f"artifacts/{CSV_REL}"))

    assert sent_paths == [f"artifacts/{CSV_REL}"]
    assert not list(csv_path.parent.glob("*.datapaw-send.*"))


def test_non_artifact_html_send_passthrough(tmp_path) -> None:
    from plugin_datapaw.core.file_delivery import build_send_file_to_user_fn

    html_path = tmp_path / "workspace" / "other.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(SAMPLE_HTML, encoding="utf-8")
    sent_paths: list[str] = []

    async def fake_host_send(file_path: str):
        sent_paths.append(file_path)
        return {"sent": file_path}

    tool = build_send_file_to_user_fn(_agent(tmp_path))
    with patch(
        "plugin_datapaw.core.file_delivery._host_send_file_to_user",
        new=fake_host_send,
    ):
        asyncio.run(tool("other.html"))

    assert sent_paths == ["other.html"]
    assert not html_path.with_name("other.datapaw-send.html").exists()


def test_html_artifact_without_session_id_passthrough(tmp_path) -> None:
    from plugin_datapaw.core.file_delivery import build_send_file_to_user_fn

    report_path = _write_artifact_report(tmp_path)
    sent_paths: list[str] = []

    async def fake_host_send(file_path: str):
        sent_paths.append(file_path)
        return {"sent": file_path}

    tool = build_send_file_to_user_fn(
        _agent(tmp_path, request_context={"agent_id": "datapaw"}),
    )
    with patch(
        "plugin_datapaw.core.file_delivery._host_send_file_to_user",
        new=fake_host_send,
    ):
        asyncio.run(tool(f"artifacts/{REPORT_REL}"))

    assert sent_paths == [f"artifacts/{REPORT_REL}"]
    assert not report_path.with_name("report.datapaw-send.html").exists()
