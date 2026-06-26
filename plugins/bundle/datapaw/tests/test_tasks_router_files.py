# -*- coding: utf-8 -*-
"""Tests for disk-backed DataPaw artifact file listing and serving."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

SESSION_ID = "session_1"
GRAPH_ID = "graph_A"
NODE_ID = "node_A"
REGISTERED_PATH = f"{SESSION_ID}/{GRAPH_ID}/{NODE_ID}/registered.csv"
UNREGISTERED_PATH = f"{SESSION_ID}/{GRAPH_ID}/{NODE_ID}/scripts/run.py"
GRAPH_ROOT_PATH = f"{SESSION_ID}/graph_B/root.csv"
SESSION_ROOT_PATH = f"{SESSION_ID}/session.json"
MISSING_REGISTERED_PATH = f"{SESSION_ID}/{GRAPH_ID}/{NODE_ID}/missing.csv"
OTHER_SESSION_PATH = "session_2/graph_A/node_A/secret.csv"


def _workspace(tmp_path):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        runner=SimpleNamespace(workspace_dir=str(workspace_dir)),
    )


def _artifacts_root(tmp_path):
    return tmp_path / "workspace" / "artifacts"


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _registered_artifacts():
    from plugin_datapaw.core.orchestration.artifact import ArtifactItem

    return [
        ArtifactItem(
            graph_id=GRAPH_ID,
            node_id=NODE_ID,
            name="registered-name.csv",
            path=REGISTERED_PATH,
            mime_type="text/registered-csv",
            size_bytes=999,
            created_at="registered-created-at",
        ),
        ArtifactItem(
            graph_id=GRAPH_ID,
            node_id=NODE_ID,
            name="missing.csv",
            path=MISSING_REGISTERED_PATH,
            mime_type="text/csv",
            size_bytes=123,
            created_at="missing-created-at",
        ),
    ]


def _write_file_tree(tmp_path) -> None:
    root = _artifacts_root(tmp_path)
    _write(root / REGISTERED_PATH, "a,b\n1,2\n")
    _write(root / UNREGISTERED_PATH, "print('ok')\n")
    _write(root / GRAPH_ROOT_PATH, "x\n1\n")
    _write(root / SESSION_ROOT_PATH, '{"ok": true}\n')
    _write(root / OTHER_SESSION_PATH, "hidden\n")


def test_list_session_artifact_files_scans_disk_and_overlays_metadata(
    tmp_path,
) -> None:
    from plugin_datapaw.core.routers.tasks_utils import (
        SESSION_ARTIFACT_GRAPH_ID,
        SESSION_ARTIFACT_ROOT_NODE_ID,
        list_session_artifact_files,
    )

    _write_file_tree(tmp_path)
    items = list_session_artifact_files(
        _workspace(tmp_path),
        SESSION_ID,
        "datapaw",
        _registered_artifacts(),
    )
    by_path = {item.path: item for item in items}

    assert set(by_path) == {
        REGISTERED_PATH,
        UNREGISTERED_PATH,
        GRAPH_ROOT_PATH,
        SESSION_ROOT_PATH,
    }

    registered = by_path[REGISTERED_PATH]
    assert registered.name == "registered-name.csv"
    assert registered.mime_type == "text/registered-csv"
    assert registered.size_bytes == 999
    assert registered.created_at == "registered-created-at"

    script = by_path[UNREGISTERED_PATH]
    assert script.graph_id == GRAPH_ID
    assert script.node_id == NODE_ID
    assert script.name == "run.py"
    assert script.size_bytes > 0
    assert script.created_at.endswith("Z")

    graph_root = by_path[GRAPH_ROOT_PATH]
    assert graph_root.graph_id == "graph_B"
    assert graph_root.node_id == SESSION_ARTIFACT_ROOT_NODE_ID

    session_root = by_path[SESSION_ROOT_PATH]
    assert session_root.graph_id == SESSION_ARTIFACT_GRAPH_ID
    assert session_root.node_id == SESSION_ARTIFACT_ROOT_NODE_ID
    assert session_root.mime_type == "application/json"


def test_list_session_artifact_files_supports_graph_and_node_filter_shape(
    tmp_path,
) -> None:
    from plugin_datapaw.core.routers.tasks_utils import list_session_artifact_files

    _write_file_tree(tmp_path)
    items = list_session_artifact_files(
        _workspace(tmp_path),
        SESSION_ID,
        "datapaw",
        _registered_artifacts(),
    )

    graph_items = [item.path for item in items if item.graph_id == GRAPH_ID]
    node_items = [
        item.path
        for item in items
        if item.graph_id == GRAPH_ID and item.node_id == NODE_ID
    ]

    assert set(graph_items) == {REGISTERED_PATH, UNREGISTERED_PATH}
    assert set(node_items) == {REGISTERED_PATH, UNREGISTERED_PATH}


def test_serve_artifact_file_allows_unregistered_preview_and_download(
    tmp_path,
) -> None:
    from plugin_datapaw.core.routers.tasks_utils import serve_artifact_file

    _write_file_tree(tmp_path)
    workspace = _workspace(tmp_path)

    preview = serve_artifact_file(
        workspace,
        SESSION_ID,
        "datapaw",
        [],
        UNREGISTERED_PATH,
        disposition="inline",
    )
    download = serve_artifact_file(
        workspace,
        SESSION_ID,
        "datapaw",
        [],
        UNREGISTERED_PATH,
        disposition="attachment",
    )

    assert preview.path == (_artifacts_root(tmp_path) / UNREGISTERED_PATH).resolve()
    assert download.path == (_artifacts_root(tmp_path) / UNREGISTERED_PATH).resolve()
    assert "run.py" in download.headers["content-disposition"]


def test_serve_artifact_file_rewrites_unregistered_html_resources(
    tmp_path,
) -> None:
    from urllib.parse import quote

    from plugin_datapaw.core.routers.tasks_utils import serve_artifact_file

    html_path = f"{SESSION_ID}/{GRAPH_ID}/{NODE_ID}/report.html"
    css_path = f"{SESSION_ID}/{GRAPH_ID}/{NODE_ID}/assets/report.css"
    root = _artifacts_root(tmp_path)
    _write(
        root / html_path,
        '<html><head><link rel="stylesheet" href="./assets/report.css"></head></html>',
    )
    _write(root / css_path, "body {}\n")

    response = serve_artifact_file(
        _workspace(tmp_path),
        SESSION_ID,
        "datapaw",
        [],
        html_path,
        disposition="inline",
        rewrite_html=True,
        user_id="default",
        api_origin="http://testserver",
    )

    body = response.body.decode("utf-8")
    assert (
        f"http://testserver/api/tasks/{SESSION_ID}/files/resource"
        f"?path={quote(css_path, safe='')}"
        in body
    )


def test_serve_resource_file_rejects_other_session_and_escape(tmp_path) -> None:
    from fastapi import HTTPException

    from plugin_datapaw.core.routers.tasks_utils import serve_resource_file

    _write_file_tree(tmp_path)
    workspace = _workspace(tmp_path)

    with pytest.raises(HTTPException) as other_session:
        serve_resource_file(
            workspace,
            SESSION_ID,
            "datapaw",
            OTHER_SESSION_PATH,
        )
    assert other_session.value.status_code == 400

    with pytest.raises(HTTPException) as escape:
        serve_resource_file(
            workspace,
            SESSION_ID,
            "datapaw",
            "../secret.txt",
        )
    assert escape.value.status_code == 400
