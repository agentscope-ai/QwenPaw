# -*- coding: utf-8 -*-
"""Tests for HTML artifact resource-link rewriting and resource proxy."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote

import pytest

SESSION_ID = "1778472702210"
REPORT_PATH = f"{SESSION_ID}/graph_ATp6bnvQ/generate_report/report.html"
CSV_PATH = f"{SESSION_ID}/graph_ATp6bnvQ/anomaly_detection/anomaly_points.csv"
CSS_PATH = f"{SESSION_ID}/graph_ATp6bnvQ/generate_report/assets/report.css"

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="https://example.com/app.css">
  <link rel="stylesheet" href="./assets/report.css">
  <style>.hero { background: url('../images/hero.png'); }</style>
</head>
<body>
  <a href="1778472702210/graph_ATp6bnvQ/anomaly_detection/anomaly_points.csv">csv</a>
  <a href="#summary">anchor</a>
  <img srcset="./small.png 1x, ./large.png 2x">
</body>
</html>
""".strip()


def _workspace(tmp_path):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        runner=SimpleNamespace(workspace_dir=str(workspace_dir)),
    )


def _write_artifact_tree(tmp_path) -> None:
    artifacts_root = tmp_path / "workspace" / "artifacts"
    (artifacts_root / "1778472702210/graph_ATp6bnvQ/generate_report").mkdir(
        parents=True,
        exist_ok=True,
    )
    (artifacts_root / "1778472702210/graph_ATp6bnvQ/anomaly_detection").mkdir(
        parents=True,
        exist_ok=True,
    )
    (artifacts_root / CSS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (artifacts_root / REPORT_PATH).write_text(SAMPLE_HTML, encoding="utf-8")
    (artifacts_root / CSV_PATH).write_text("date,dau\n2025-12-01,1\n", encoding="utf-8")
    (artifacts_root / CSS_PATH).write_text("body {}", encoding="utf-8")


def _report_artifact():
    from plugin_datapaw.core.orchestration.artifact import ArtifactItem

    return ArtifactItem(
        graph_id="g1",
        node_id="n1",
        name="report.html",
        path=REPORT_PATH,
        mime_type="text/html",
        size_bytes=1,
    )


def test_build_resource_url_absolute() -> None:
    from plugin_datapaw.core.routers.tasks_utils import build_resource_url

    url = build_resource_url(
        "s1",
        CSV_PATH,
        user_id="default",
        agent_id="datapaw",
        api_origin="http://127.0.0.1:8088",
    )

    assert url == (
        "http://127.0.0.1:8088/api/tasks/s1/files/resource"
        f"?path={quote(CSV_PATH, safe='')}"
        "&user_id=default&agent_id=datapaw"
    )


def test_rewrite_html_resource_links_absolute() -> None:
    from plugin_datapaw.core.routers.tasks_utils import rewrite_html_resource_links

    rewritten = rewrite_html_resource_links(
        SAMPLE_HTML,
        html_path=REPORT_PATH,
        session_id="s1",
        user_id="default",
        agent_id="datapaw",
        api_origin="http://testserver",
    )

    csv_url = (
        "http://testserver/api/tasks/s1/files/resource"
        f"?path={quote(CSV_PATH, safe='')}"
        "&amp;user_id=default&amp;agent_id=datapaw"
    )
    assert csv_url in rewritten


def test_rewrite_html_resource_links_unit() -> None:
    from plugin_datapaw.core.routers.tasks_utils import rewrite_html_resource_links

    rewritten = rewrite_html_resource_links(
        SAMPLE_HTML,
        html_path=REPORT_PATH,
        session_id="s1",
        user_id="default",
    )

    csv_url = (
        f"/api/tasks/s1/files/resource?path={quote(CSV_PATH, safe='')}"
        "&amp;user_id=default"
    )
    css_url = (
        f"/api/tasks/s1/files/resource?path={quote(CSS_PATH, safe='')}"
        "&amp;user_id=default"
    )
    assert csv_url in rewritten
    assert css_url in rewritten
    assert "https://example.com/app.css" in rewritten
    assert 'href="#summary"' in rewritten
    assert (
        f"/api/tasks/s1/files/resource?path={quote('1778472702210/graph_ATp6bnvQ/generate_report/small.png', safe='')}"
        in rewritten
    )


def test_serve_artifact_file_preview_rewrites(tmp_path) -> None:
    from plugin_datapaw.core.routers.tasks_utils import serve_artifact_file

    _write_artifact_tree(tmp_path)
    workspace = _workspace(tmp_path)
    response = serve_artifact_file(
        workspace,
        SESSION_ID,
        "datapaw",
        [_report_artifact()],
        REPORT_PATH,
        disposition="inline",
        rewrite_html=True,
        user_id="default",
        api_origin="http://testserver",
    )

    body = response.body.decode("utf-8")
    assert (
        f"http://testserver/api/tasks/{SESSION_ID}/files/resource"
        f"?path={quote(CSV_PATH, safe='')}"
        in body
    )
    assert (
        f"http://testserver/api/tasks/{SESSION_ID}/files/resource"
        f"?path={quote(CSS_PATH, safe='')}"
        in body
    )
    assert "&amp;agent_id=datapaw" in body


def test_serve_artifact_file_download_rewrites(tmp_path) -> None:
    from plugin_datapaw.core.routers.tasks_utils import serve_artifact_file

    _write_artifact_tree(tmp_path)
    workspace = _workspace(tmp_path)
    response = serve_artifact_file(
        workspace,
        SESSION_ID,
        "datapaw",
        [_report_artifact()],
        REPORT_PATH,
        disposition="attachment",
        rewrite_html=True,
        user_id="default",
        api_origin="http://testserver",
    )

    body = response.body.decode("utf-8")
    assert (
        f"http://testserver/api/tasks/{SESSION_ID}/files/resource"
        f"?path={quote(CSV_PATH, safe='')}"
        in body
    )
    assert "Content-Disposition" in response.headers
    assert "attachment" in response.headers["Content-Disposition"]


def test_serve_resource_file_serves_under_artifact_root(tmp_path) -> None:
    from plugin_datapaw.core.routers.tasks_utils import serve_resource_file

    _write_artifact_tree(tmp_path)
    workspace = _workspace(tmp_path)
    response = serve_resource_file(
        workspace,
        SESSION_ID,
        "datapaw",
        CSV_PATH,
    )

    assert response.path == (
        tmp_path / "workspace" / "artifacts" / CSV_PATH
    ).resolve()


def test_serve_resource_file_rejects_paths_outside_artifact_root(tmp_path) -> None:
    from fastapi import HTTPException

    from plugin_datapaw.core.routers.tasks_utils import serve_resource_file

    _write_artifact_tree(tmp_path)
    workspace = _workspace(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        serve_resource_file(
            workspace,
            SESSION_ID,
            "datapaw",
            "../secret.txt",
        )

    assert exc_info.value.status_code == 400


def test_resolve_request_api_origin_uses_forwarded_headers() -> None:
    from starlette.requests import Request

    from plugin_datapaw.core.routers.tasks_utils import resolve_request_api_origin

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/tasks/s1/files/preview",
        "headers": [
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-host", b"pre-datapaw-cloud.alibaba-inc.com"),
            (b"host", b"10.0.0.1:8088"),
        ],
        "query_string": b"",
        "server": ("10.0.0.1", 8088),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "http_version": "1.1",
    }
    request = Request(scope)

    assert (
        resolve_request_api_origin(request)
        == "https://pre-datapaw-cloud.alibaba-inc.com"
    )
