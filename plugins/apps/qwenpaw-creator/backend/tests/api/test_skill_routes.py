# -*- coding: utf-8 -*-
# pylint: disable=protected-access,wrong-import-order
"""Skill routes: discovery stays off the loop; content reads the raw file."""

from __future__ import annotations

import io
import json
import threading
import zipfile

from fastapi import FastAPI
import pytest
from starlette.datastructures import UploadFile

from api import skill_routes
from api.dependencies import creator_error_handler
from domain.errors import CreatorError
from models import config
from qwenpaw.exceptions import SkillsError
from services import external_skills
from services.media_files import user_skills
from services.skill_hub import (
    HubBundle,
    SkillHubTimeout,
    SkillHubUnavailable,
    SkillHubUrlError,
)

pytestmark = pytest.mark.unit

_SKILL_MD = """---
name: demo-skill
description: demo
---

# Demo
"""


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(skill_routes.router)
    return app


@pytest.fixture(autouse=True)
def _reset_caches():
    yield
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()


def _configure(tmp_path, monkeypatch, entries):
    data_root = tmp_path / "creator-data"
    (data_root / "config").mkdir(parents=True, exist_ok=True)
    (data_root / "config" / "skills_config.json").write_text(
        json.dumps({"skills": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.delenv("CREATOR_SKILLS_CONFIG_PATH", raising=False)
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()
    return data_root


def _write_demo_skill(tmp_path):
    root = tmp_path / "demo-src"
    root.mkdir()
    (root / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    return root


def test_list_skills_runs_off_the_event_loop(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    """Skill discovery scans disk (and may probe node); never on the loop."""

    root = _write_demo_skill(tmp_path)
    _configure(
        tmp_path,
        monkeypatch,
        [{"name": "demo-skill", "path": str(root), "enabled": True}],
    )
    load_threads: list[int] = []
    real_load = skill_routes.load_skills

    def recording_load():
        load_threads.append(threading.get_ident())
        return real_load()

    monkeypatch.setattr(skill_routes, "load_skills", recording_load)

    async def scenario(client) -> int:
        loop_thread = threading.get_ident()
        response = await client.get("/skills")
        assert response.status_code == 200, response.text
        names = [item["name"] for item in response.json()["items"]]
        assert "demo-skill" in names
        return loop_thread

    loop_thread = run_scenario(_app(), scenario)
    assert load_threads, "list_skills must discover skills"
    assert all(thread != loop_thread for thread in load_threads)


def test_get_skill_content_runs_off_the_event_loop(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    """The content read (find_skill -> load_skills) is off the loop too."""

    root = _write_demo_skill(tmp_path)
    _configure(
        tmp_path,
        monkeypatch,
        [{"name": "demo-skill", "path": str(root), "enabled": True}],
    )
    read_threads: list[int] = []
    real_read = skill_routes.read_skill_content

    def recording_read(**kwargs):
        read_threads.append(threading.get_ident())
        return real_read(**kwargs)

    monkeypatch.setattr(skill_routes, "read_skill_content", recording_read)

    async def scenario(client) -> int:
        loop_thread = threading.get_ident()
        response = await client.get("/skills/demo-skill/content")
        assert response.status_code == 200, response.text
        assert response.json()["content"] == _SKILL_MD
        return loop_thread

    loop_thread = run_scenario(_app(), scenario)
    assert read_threads, "get_skill_content must read the skill"
    assert all(thread != loop_thread for thread in read_threads)


def test_content_route_reads_a_disabled_skill(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """The editor reads a disabled skill's raw SKILL.md (view_skill can't)."""

    root = _write_demo_skill(tmp_path)
    _configure(
        tmp_path,
        monkeypatch,
        [{"name": "demo-skill", "path": str(root), "enabled": False}],
    )
    response = api_request(_app(), "GET", "/skills/demo-skill/content")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"] == _SKILL_MD
    assert body["truncated"] is False


def test_content_route_404_for_unknown_skill(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """An unknown skill maps SkillExecutionError to a 404."""

    _configure(tmp_path, monkeypatch, [])
    response = api_request(_app(), "GET", "/skills/nope/content")
    assert response.status_code == 404


def test_save_skill_runs_off_the_event_loop(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    """The locked read-modify-write never blocks the ASGI loop either.

    Saving waits on the module-wide skills_config lock and does disk IO, so
    running it on the loop would stall every other request while a ZIP import
    worker holds the lock.
    """

    _configure(tmp_path, monkeypatch, [])
    save_threads: list[int] = []
    save_overwrite: list[bool] = []
    real_save = skill_routes.save_user_skill

    def recording_save(name, content, *, overwrite=False):
        save_threads.append(threading.get_ident())
        save_overwrite.append(overwrite)
        return real_save(name, content, overwrite=overwrite)

    monkeypatch.setattr(skill_routes, "save_user_skill", recording_save)

    async def scenario(client) -> int:
        loop_thread = threading.get_ident()
        response = await client.post(
            "/skills",
            json={"name": "demo-skill", "content": _SKILL_MD},
        )
        assert response.status_code == 200, response.text
        # Absent flag means create, which must never replace a same-named
        # skill; the edit states its intent explicitly.
        assert save_overwrite == [False]
        response = await client.post(
            "/skills",
            json={
                "name": "demo-skill",
                "content": _SKILL_MD,
                "overwrite": True,
            },
        )
        assert response.status_code == 200, response.text
        assert save_overwrite == [False, True]
        return loop_thread

    loop_thread = run_scenario(_app(), scenario)
    assert save_threads, "save_skill must write the skill"
    assert all(thread != loop_thread for thread in save_threads)


def test_refused_skill_write_surfaces_as_400(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """UserSkillError raised inside the worker thread still maps to a 400."""

    _configure(tmp_path, monkeypatch, [])

    def refuse(name, content, *, overwrite=False):
        raise skill_routes.UserSkillError("技能名与内置技能同名: demo")

    monkeypatch.setattr(skill_routes, "save_user_skill", refuse)
    response = api_request(
        _app(),
        "POST",
        "/skills",
        json={"name": "demo-skill", "content": _SKILL_MD},
    )
    assert response.status_code == 400
    assert "内置" in json.dumps(response.json(), ensure_ascii=False)


def test_duplicate_create_is_refused_through_the_route(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """The create/edit intent survives the HTTP layer, not just the service.

    A second POST without overwrite names a skill that is now registered, so
    it must surface the 400 refusal instead of silently replacing the first.
    """

    _configure(tmp_path, monkeypatch, [])
    app = _app()
    created = api_request(
        app,
        "POST",
        "/skills",
        json={"name": "demo-skill", "content": _SKILL_MD},
    )
    assert created.status_code == 200, created.text

    duplicate = api_request(
        app,
        "POST",
        "/skills",
        json={"name": "demo-skill", "content": _SKILL_MD},
    )
    assert duplicate.status_code == 400
    assert "已存在" in json.dumps(duplicate.json(), ensure_ascii=False)

    edited = api_request(
        app,
        "POST",
        "/skills",
        json={
            "name": "demo-skill",
            "content": _SKILL_MD,
            "overwrite": True,
        },
    )
    assert edited.status_code == 200, edited.text


def _bundle(name: str = "hub-skill", content: str = _SKILL_MD, ignored=0):
    return HubBundle(
        name=name,
        content=content,
        source_url="https://skills.sh/acme/skills/hub-skill",
        installed_from="skills-sh",
        ignored_files=ignored,
    )


def _fake_fetch(monkeypatch, bundle, calls=None):
    async def fake(bundle_url, *, version="", target_name=None):
        if calls is not None:
            calls.append((bundle_url, version, target_name))
        return bundle

    monkeypatch.setattr(skill_routes, "fetch_skill_bundle", fake)


def test_url_import_lands_the_fetched_skill(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """A hub bundle is written through the managed create and registered."""

    data_root = _configure(tmp_path, monkeypatch, [])
    _fake_fetch(monkeypatch, _bundle(ignored=3))
    response = api_request(
        _app(),
        "POST",
        "/skills/import-url",
        json={"bundle_url": "https://skills.sh/acme/skills/hub-skill"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == ["hub-skill"]
    assert body["ignored_files"] == 3
    assert (data_root / "skills" / "hub-skill" / "SKILL.md").read_text(
        encoding="utf-8",
    ) == _SKILL_MD
    listing = api_request(_app(), "GET", "/skills").json()["items"]
    assert "hub-skill" in [item["name"] for item in listing]


def test_url_import_forwards_the_optional_target_name(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """The pane may pin the skill name instead of the remote one."""

    _configure(tmp_path, monkeypatch, [])
    calls: list[tuple] = []
    _fake_fetch(monkeypatch, _bundle(name="pinned-skill"), calls)
    response = api_request(
        _app(),
        "POST",
        "/skills/import-url",
        json={
            "bundle_url": "https://skills.sh/acme/skills/hub-skill",
            "target_name": "  pinned-skill  ",
        },
    )
    assert response.status_code == 200, response.text
    assert calls[0][2] == "pinned-skill"


def test_url_import_refuses_a_duplicate_name_without_writing(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """An import is a create: it must not replace an owned name.

    The second bundle carries different content, so the first SKILL.md still
    holding its bytes proves the refusal happens before anything is written.
    """

    data_root = _configure(tmp_path, monkeypatch, [])
    app = _app()
    _fake_fetch(monkeypatch, _bundle())
    first = api_request(
        app,
        "POST",
        "/skills/import-url",
        json={"bundle_url": "https://skills.sh/acme/skills/hub-skill"},
    )
    assert first.status_code == 200, first.text
    skill_md = data_root / "skills" / "hub-skill" / "SKILL.md"
    before = skill_md.read_text(encoding="utf-8")

    replaced = _bundle(content=_SKILL_MD.replace("demo", "other"))
    _fake_fetch(monkeypatch, replaced)
    duplicate = api_request(
        app,
        "POST",
        "/skills/import-url",
        json={"bundle_url": "https://skills.sh/acme/skills/hub-skill"},
    )
    assert duplicate.status_code == 400
    assert "已存在" in json.dumps(duplicate.json(), ensure_ascii=False)
    assert skill_md.read_text(encoding="utf-8") == before


def test_url_import_write_runs_off_the_event_loop(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    """Same rule as every other skill writer: lock + disk IO off the loop."""

    _configure(tmp_path, monkeypatch, [])
    _fake_fetch(monkeypatch, _bundle())
    write_threads: list[int] = []
    real_install = skill_routes.install_skill_from_hub_bundle

    def recording_install(bundle):
        write_threads.append(threading.get_ident())
        return real_install(bundle)

    monkeypatch.setattr(
        skill_routes,
        "install_skill_from_hub_bundle",
        recording_install,
    )

    async def scenario(client) -> int:
        loop_thread = threading.get_ident()
        response = await client.post(
            "/skills/import-url",
            json={"bundle_url": "https://skills.sh/acme/skills/hub-skill"},
        )
        assert response.status_code == 200, response.text
        return loop_thread

    loop_thread = run_scenario(_app(), scenario)
    assert write_threads, "the import must write the skill"
    assert all(thread != loop_thread for thread in write_threads)


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (SkillHubUrlError("URL 需以 http:// 或 https:// 开头"), 400),
        (SkillHubUnavailable("当前 QwenPaw 运行时未提供技能中心"), 501),
        (SkillHubTimeout("从 URL 获取技能超时（90s）"), 504),
        # The host's own fetch failures, mapped exactly like its Pool route.
        (SkillsError(message="market unreachable"), 400),
    ),
)
def test_url_import_maps_fetch_failures_to_http_status(
    tmp_path,
    monkeypatch,
    api_request,
    failure,
    expected,
) -> None:
    """Every fetch outcome surfaces as a refusal, never a bare 500."""

    _configure(tmp_path, monkeypatch, [])

    async def refuse(bundle_url, *, version="", target_name=None):
        raise failure

    monkeypatch.setattr(skill_routes, "fetch_skill_bundle", refuse)
    response = api_request(
        _app(),
        "POST",
        "/skills/import-url",
        json={"bundle_url": "https://skills.sh/acme/skills/hub-skill"},
    )
    assert response.status_code == expected
    # The reason survives the HTTP layer verbatim: a bare 500 or a generic
    # "import failed" would leave the user guessing about the URL.
    assert str(failure) in json.dumps(
        response.json(),
        ensure_ascii=False,
    )


def test_upload_refuses_an_oversized_body_before_reading_it(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """The declared length is enough to refuse: no spool, no parse.

    ``request.form()`` spools the upload to a temporary file and ``read()``
    then pulls it into memory, so the importer's own size check used to run
    only after both had happened.
    """

    _configure(tmp_path, monkeypatch, [])
    cap = 1024 * 1024
    monkeypatch.setattr(skill_routes, "MAX_SKILL_ZIP_BYTES", cap)
    monkeypatch.setattr(user_skills, "MAX_SKILL_ZIP_BYTES", cap)

    def refuse(*_args, **_kwargs):
        raise AssertionError("an over-limit body must not reach the importer")

    monkeypatch.setattr(skill_routes, "import_skills_from_zip_bytes", refuse)
    response = api_request(
        _app(),
        "POST",
        "/skills/upload",
        files={"file": ("skills.zip", b"z" * (cap + 1), "application/zip")},
    )
    assert response.status_code == 400
    assert "ZIP 超过 1MB 上限" in json.dumps(
        response.json(),
        ensure_ascii=False,
    )


def test_upload_reads_at_most_one_byte_past_the_cap(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """A chunked upload declares no length, so the read itself stays bounded.

    Reading cap + 1 is enough to refuse while keeping an over-limit body out
    of memory, and the importer re-checks because it is reachable without
    this route.
    """

    data_root = _configure(tmp_path, monkeypatch, [])
    monkeypatch.setattr(skill_routes, "MAX_SKILL_ZIP_BYTES", 4096)
    sizes: list[int] = []
    real_read = UploadFile.read

    async def recording_read(self, size=-1):
        sizes.append(size)
        return await real_read(self, size)

    monkeypatch.setattr(UploadFile, "read", recording_read)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("demo/SKILL.md", _SKILL_MD)

    response = api_request(
        _app(),
        "POST",
        "/skills/upload",
        files={
            "file": (
                "skills.zip",
                payload.getvalue(),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 200, response.text
    assert sizes == [4097]
    assert response.json()["imported"] == ["demo-skill"]
    assert (data_root / "skills" / "demo-skill" / "SKILL.md").is_file()


def test_save_route_refuses_an_oversized_document_without_writing(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    """The request schema bounds the name but not the body.

    The document cap lives in the writer, so the editor save is bounded by the
    same number as a ZIP member or a hub bundle instead of writing whatever
    the client sent.
    """

    data_root = _configure(tmp_path, monkeypatch, [])
    monkeypatch.setattr(user_skills, "_MAX_SKILL_DOC_BYTES", 2048)
    response = api_request(
        _app(),
        "POST",
        "/skills",
        json={"name": "huge", "content": _SKILL_MD + "x" * 4096},
    )
    assert response.status_code == 400
    assert "超过 2KB 上限" in json.dumps(
        response.json(),
        ensure_ascii=False,
    )
    assert not list((data_root / "skills").iterdir())
    assert not config.load_skills_config()
