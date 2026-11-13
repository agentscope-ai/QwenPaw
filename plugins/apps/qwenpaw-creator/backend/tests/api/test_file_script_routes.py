# -*- coding: utf-8 -*-
"""剧本直登 HTTP 通道：前端剧本页把写好的正文直接落成 timeline_script 版本。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI

from api import file_script_routes
from api.dependencies import creator_error_handler, project_file_services
from api.router import router
from domain.errors import CreatorError
from services.project_files.assets import AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.project_files.script_artifacts import timeline_script_slot_id
from services.project_files.script_import import ScriptImportError

PROJECT_ID = "project-1"
TIMELINE_ID = "timeline:main"
SCRIPT_TEXT = "## 场 1 · 内景 · 旧宅大厅 · 夜\n\n林晚推门进来。\n\n**林晚**（低声）：我回来了。\n"
REVISED_TEXT = "## 场 1 · 改稿 B\n\n新的开场。\n"

pytestmark = [
    pytest.mark.integration,
    # 路由面需要可解析的 model config；fixture 把 CREATOR_DATA_ROOT 指向本用例
    # 的临时目录并隔离服务注册表。
    pytest.mark.usefixtures("api_runtime_root"),
]


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Script Import Project"),
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services


def _url(timeline_id: str = TIMELINE_ID) -> str:
    return f"/projects/{PROJECT_ID}/timelines/{timeline_id}/script-import"


def test_upload_lands_selected_script_version(tmp_path, run_scenario) -> None:
    app, services = _app(tmp_path)

    async def scenario(client):
        return await client.post(
            _url(),
            files={
                "file": (
                    "我的剧本.md",
                    SCRIPT_TEXT.encode("utf-8"),
                    "text/markdown",
                ),
            },
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["resultKind"] == "script_import"
    assert payload["replayed"] is False
    assert payload["reviewId"] is None
    assert payload["blockCount"] == 3
    assert payload["changedPointers"]

    snapshot = services.projects.read(PROJECT_ID)
    slot = snapshot.project.assets.artifact_slots_by_id[
        timeline_script_slot_id(TIMELINE_ID)
    ]
    assert slot.selected_version_id == payload["artifactVersionId"]
    version = snapshot.project.assets.artifact_versions_by_id[
        payload["artifactVersionId"]
    ]
    assert version.metadata["source"] == "script_import"
    assert version.metadata["importedFromName"] == "我的剧本.md"
    # 正文真落在项目里，剧本页可以直接读该 artifact 版本渲染。
    indexed = snapshot.project.assets.files_by_id[payload["fileId"]]
    body = (
        AssetFileStore(services.projects.project_root(PROJECT_ID))
        .open_verified(indexed)
        .read()
        .decode("utf-8")
    )
    assert "我回来了" in body
    # 直登不建 ProjectSource：素材理解链路完全没有被唤醒。
    assert snapshot.project.sources.sources.items == {}


def test_pasted_text_and_repeat_import_replays(tmp_path, run_scenario) -> None:
    app, services = _app(tmp_path)
    base_generation = services.projects.read(PROJECT_ID).generation

    async def scenario(client):
        first = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT, "name": "粘贴剧本"},
        )
        second = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT, "name": "粘贴剧本"},
        )
        return first, second

    first, second = run_scenario(app, scenario)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["replayed"] is True
    assert (
        second.json()["artifactVersionId"] == first.json()["artifactVersionId"]
    )
    assert second.json()["generation"] == first.json()["generation"]
    # 复放不制造空生成，也不改项目名。
    snapshot = services.projects.read(PROJECT_ID)
    assert snapshot.generation == base_generation + 1
    assert snapshot.project.name == "Script Import Project"


def test_revised_script_appends_new_version(tmp_path, run_scenario) -> None:
    app, services = _app(tmp_path)

    async def scenario(client):
        await client.post(_url(), json={"content": SCRIPT_TEXT})
        return await client.post(
            _url(),
            json={"content": "## 场 1 · 改稿\n\n新的开场。\n"},
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 201, response.text
    slot = services.projects.read(
        PROJECT_ID,
    ).project.assets.artifact_slots_by_id[timeline_script_slot_id(TIMELINE_ID)]
    assert len(slot.version_ids) == 2
    assert slot.selected_version_id == response.json()["artifactVersionId"]


def test_reimporting_a_previous_script_returns_201_not_500(
    tmp_path,
    run_scenario,
) -> None:
    """A→B→A 走真实 HTTP 路由：三次都 201，第三次不再撞旧事务 500。

    回归：事务身份此前由正文 checksum 派生，重新选用旧稿 A 会复用第一
    次 A 已提交的事务，提交边界抛 ProjectCommitError，路由返回 500
    （状态序列 [201, 201, 500]）。每次编辑改用独立事务后三次都成功。
    """
    app, services = _app(tmp_path)

    async def scenario(client):
        first = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT},
            headers={"Idempotency-Key": "script-import-a"},
        )
        second = await client.post(
            _url(),
            json={"content": REVISED_TEXT},
            headers={"Idempotency-Key": "script-import-b"},
        )
        third = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT},
            headers={"Idempotency-Key": "script-import-c"},
        )
        return first, second, third

    first, second, third = run_scenario(app, scenario)
    assert [first.status_code, second.status_code, third.status_code] == [
        201,
        201,
        201,
    ], (first.text, second.text, third.text)
    assert third.json()["replayed"] is False
    assert (
        third.json()["artifactVersionId"] == first.json()["artifactVersionId"]
    )
    slot = services.projects.read(
        PROJECT_ID,
    ).project.assets.artifact_slots_by_id[timeline_script_slot_id(TIMELINE_ID)]
    assert slot.selected_version_id == first.json()["artifactVersionId"]


def test_retrying_a_completed_key_after_an_interleaved_edit_replays(
    tmp_path,
    run_scenario,
) -> None:
    """交错编辑后重试同一请求：A/key-a、B/key-b、再重试 A/key-a。

    回归：幂等键此前只转成固定 transaction_id，并不回放已完成结果。响应
    丢失后重试 A/key-a，早返回（只比当前选中内容）不成立，提交边界收到已
    COMMITTED 的事务 ID 抛 ProjectCommitError，路由返回 500（[201,201,500]）。
    现在已完成请求被持久记录，重试直接回放 A 的结果（201），且不把当前 B
    覆盖回 A。
    """
    app, services = _app(tmp_path)

    async def scenario(client):
        first = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT},
            headers={"Idempotency-Key": "script-import-a"},
        )
        second = await client.post(
            _url(),
            json={"content": REVISED_TEXT},
            headers={"Idempotency-Key": "script-import-b"},
        )
        retry = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT},
            headers={"Idempotency-Key": "script-import-a"},
        )
        return first, second, retry

    first, second, retry = run_scenario(app, scenario)
    assert [first.status_code, second.status_code, retry.status_code] == [
        201,
        201,
        201,
    ], (first.text, second.text, retry.text)
    # 重试回放 A 的已完成结果，版本与首次一致。
    assert (
        retry.json()["artifactVersionId"] == first.json()["artifactVersionId"]
    )
    # 关键：回放不把当前剧本从 B 覆盖回 A。
    slot = services.projects.read(
        PROJECT_ID,
    ).project.assets.artifact_slots_by_id[timeline_script_slot_id(TIMELINE_ID)]
    assert slot.selected_version_id == second.json()["artifactVersionId"]


def test_reusing_a_key_with_a_different_payload_is_a_conflict(
    tmp_path,
    run_scenario,
) -> None:
    """同一个 Idempotency-Key 用于不同正文：明确 409 冲突，不是 500。"""
    app, _services = _app(tmp_path)

    async def scenario(client):
        first = await client.post(
            _url(),
            json={"content": SCRIPT_TEXT},
            headers={"Idempotency-Key": "script-import-a"},
        )
        conflict = await client.post(
            _url(),
            json={"content": REVISED_TEXT},
            headers={"Idempotency-Key": "script-import-a"},
        )
        return first, conflict

    first, conflict = run_scenario(app, scenario)
    assert first.status_code == 201, first.text
    assert conflict.status_code == 409, conflict.text
    body = conflict.json()
    assert body["code"] == "CONFLICT"
    assert body["details"]["code"] == "SCRIPT_IMPORT_IDEMPOTENCY_CONFLICT"


def test_replay_file_id_resolves_to_the_indexed_file(
    tmp_path,
    run_scenario,
) -> None:
    """复放返回的 fileId 是文件索引里的键，不是重复的 artifactVersionId。"""
    app, services = _app(tmp_path)

    async def scenario(client):
        first = await client.post(_url(), json={"content": SCRIPT_TEXT})
        replay = await client.post(_url(), json={"content": SCRIPT_TEXT})
        return first, replay

    first, replay = run_scenario(app, scenario)
    assert first.status_code == 201 and replay.status_code == 201
    assert replay.json()["replayed"] is True
    file_id = replay.json()["fileId"]
    assert file_id == first.json()["fileId"]
    assert file_id != replay.json()["artifactVersionId"]
    snapshot = services.projects.read(PROJECT_ID)
    assert file_id in snapshot.project.assets.files_by_id
    # fileId 能真正读到剧本正文，依赖它的调用方不会落空。
    indexed = snapshot.project.assets.files_by_id[file_id]
    body = (
        AssetFileStore(services.projects.project_root(PROJECT_ID))
        .open_verified(indexed)
        .read()
        .decode("utf-8")
    )
    assert "我回来了" in body


def test_unknown_timeline_is_not_found(tmp_path, run_scenario) -> None:
    app, _services = _app(tmp_path)

    async def scenario(client):
        return await client.post(
            _url("timeline:ghost"),
            json={"content": SCRIPT_TEXT},
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 404
    body = response.json()
    assert "timeline 不存在" in body["message"]
    # NotFoundError.code 只有笼统的 NOT_FOUND，具体原因走 details。
    assert body["details"]["code"] == "SCRIPT_IMPORT_TIMELINE_NOT_FOUND"


def test_snapshot_timeline_is_refused(tmp_path, run_scenario) -> None:
    app, services = _app(tmp_path)
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"]["snapshot:timeline:main:1"] = {
        "timeline_id": "snapshot:timeline:main:1",
        "title": "历史副本",
    }
    candidate["timelines"]["order"].append("snapshot:timeline:main:1")
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
    )

    async def scenario(client):
        return await client.post(
            _url("snapshot:timeline:main:1"),
            json={"content": SCRIPT_TEXT},
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 422
    assert "历史副本" in response.json()["message"]


def test_non_text_and_undecodable_uploads_are_rejected(
    tmp_path,
    run_scenario,
) -> None:
    app, _services = _app(tmp_path)

    async def scenario(client):
        binary = await client.post(
            _url(),
            files={
                "file": (
                    "shot.png",
                    b"\x89PNG\r\n\x1a\n\x00\x01",
                    "image/png",
                ),
            },
        )
        gbk = await client.post(
            _url(),
            files={"file": ("旧剧本.txt", "剧本正文".encode("gbk"), "text/plain")},
        )
        empty = await client.post(_url(), json={"content": "   "})
        return binary, gbk, empty

    binary, gbk, empty = run_scenario(app, scenario)
    assert binary.status_code == 422
    assert "只接受 UTF-8 文本" in binary.json()["message"]
    # 图片不是剧本载体，报错要顺手指出哪些文档后缀可以直登。
    assert ".docx" in binary.json()["message"]
    assert ".pdf" in binary.json()["message"]
    assert gbk.status_code == 422
    assert "不是 UTF-8" in gbk.json()["message"]
    assert empty.status_code == 422
    assert "非空 content" in empty.json()["message"]
    # 前置拒绝也必须带具体 code：HTTP 侧与 Agent 侧同一个失败同一个身份。
    assert binary.json()["details"]["code"] == "SCRIPT_IMPORT_NOT_TEXT"
    assert gbk.json()["details"]["code"] == "SCRIPT_IMPORT_NOT_UTF8"
    assert empty.json()["details"]["code"] == "SCRIPT_IMPORT_EMPTY"


def test_document_upload_lands_the_extracted_text(
    tmp_path,
    run_scenario,
    monkeypatch,
) -> None:
    """写在 Word 里的剧本走同一条直登路，不再被逐页当图片理解。

    真实渲染依赖（LibreOffice/pdfium）不在集测范围，这里只钉住路由的
    分支与产物：抽出的正文落版本、不建 ProjectSource、名字进元数据。
    """

    app, services = _app(tmp_path)
    extracted: list[str] = []

    def fake_extract(data: bytes, *, name: str) -> str:
        extracted.append(name)
        assert data == b"PK\x03\x04-fake-docx"
        return SCRIPT_TEXT

    monkeypatch.setattr(
        file_script_routes,
        "extract_script_document_text",
        fake_extract,
    )

    async def scenario(client):
        return await client.post(
            _url(),
            files={
                "file": (
                    "我的剧本.docx",
                    b"PK\x03\x04-fake-docx",
                    "application/octet-stream",
                ),
            },
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["resultKind"] == "script_import"
    assert payload["blockCount"] == 3
    assert extracted == ["我的剧本.docx"]

    snapshot = services.projects.read(PROJECT_ID)
    version = snapshot.project.assets.artifact_versions_by_id[
        payload["artifactVersionId"]
    ]
    assert version.metadata["importedFromName"] == "我的剧本.docx"
    # 直登不建 ProjectSource：文档理解链路完全没有被唤醒。
    assert snapshot.project.sources.sources.items == {}


def test_extraction_failure_surfaces_as_a_readable_422(
    tmp_path,
    run_scenario,
    monkeypatch,
) -> None:
    """抽正文发生在落版本之前，也必须经 ``_translate`` 变成 4xx。"""

    app, services = _app(tmp_path)

    def fake_extract(data: bytes, *, name: str) -> str:
        raise ScriptImportError(
            f"{name} 抽不出可用正文：扫描件没有文字层。",
            code="SCRIPT_IMPORT_DOCUMENT_NO_TEXT",
        )

    monkeypatch.setattr(
        file_script_routes,
        "extract_script_document_text",
        fake_extract,
    )

    async def scenario(client):
        return await client.post(
            _url(),
            files={"file": ("扫描剧本.pdf", b"%PDF-1.7", "application/pdf")},
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 422
    body = response.json()
    assert "抽不出可用正文" in body["message"]
    # ValidationError.code 是类属性，前端只能靠 details.code 区分
    # 「扫描件没文字层」与「转换超时，请重试」这两种相反的下一步。
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["code"] == "SCRIPT_IMPORT_DOCUMENT_NO_TEXT"
    # 失败的直登不能留下半个剧本版本。
    snapshot = services.projects.read(PROJECT_ID)
    assert (
        timeline_script_slot_id(TIMELINE_ID)
        not in snapshot.project.assets.artifact_slots_by_id
    )


def test_oversized_document_is_refused_before_extraction(
    tmp_path,
    run_scenario,
    monkeypatch,
) -> None:
    """文档上限单独一档，且超限不该先把整份文件抽一遍再拒。"""

    app, _services = _app(tmp_path)
    monkeypatch.setattr(
        file_script_routes,
        "SCRIPT_IMPORT_DOCUMENT_MAX_BYTES",
        16,
    )
    extracted: list[str] = []

    def fake_extract(_data: bytes, *, name: str) -> str:
        extracted.append(name)
        return SCRIPT_TEXT

    monkeypatch.setattr(
        file_script_routes,
        "extract_script_document_text",
        fake_extract,
    )

    async def scenario(client):
        return await client.post(
            _url(),
            files={"file": ("长剧本.docx", b"x" * 17, "application/pdf")},
        )

    response = run_scenario(app, scenario)
    assert response.status_code == 422
    assert "文档直登上限 16 字节" in response.json()["message"]
    # 与 Agent 路径的 import_script 共用同一个 code。
    assert response.json()["details"]["code"] == "SCRIPT_IMPORT_TOO_LARGE"
    assert not extracted, "超限的文档不该启动抽取"
