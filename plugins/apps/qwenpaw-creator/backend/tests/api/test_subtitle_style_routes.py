# -*- coding: utf-8 -*-
"""CRUD round-trip for user-defined subtitle styles."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.subtitle_style_routes import router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


BUNDLE = {
    "name": "我的综艺字",
    "description": "高饱和描边",
    "packId": "variety_pop",
    "style": {"color": "#ff0000", "fontScale": 1.2},
    "animation": {"entrance": "pop", "loop": True},
}


def test_save_list_update_delete_round_trip(client) -> None:
    created = client.post("/subtitle-packs/custom", json=BUNDLE)
    assert created.status_code == 200
    item = created.json()
    assert item["styleId"].startswith("user:")
    assert item["packId"] == "variety_pop"
    assert item["style"] == {"color": "#ff0000", "fontScale": 1.2}
    assert item["animation"] == {"entrance": "pop", "loop": True}

    listed = client.get("/subtitle-packs/custom")
    assert [i["styleId"] for i in listed.json()["items"]] == [
        item["styleId"],
    ]

    updated = client.put(
        f"/subtitle-packs/custom/{item['styleId']}",
        json={**BUNDLE, "name": "改名", "style": {}},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名"
    assert updated.json()["style"] == {}

    gone = client.delete(f"/subtitle-packs/custom/{item['styleId']}")
    assert gone.status_code == 200
    assert client.get("/subtitle-packs/custom").json()["items"] == []


def test_delete_refuses_builtin_and_missing(client) -> None:
    refused = client.delete("/subtitle-packs/custom/variety_pop")
    assert refused.status_code == 400
    missing = client.delete("/subtitle-packs/custom/user:nope")
    assert missing.status_code == 404


def test_update_refuses_unknown_id(client) -> None:
    response = client.put("/subtitle-packs/custom/user:nope", json=BUNDLE)
    assert response.status_code == 404


def test_save_requires_a_name(client) -> None:
    response = client.post(
        "/subtitle-packs/custom",
        json={**BUNDLE, "name": "  "},
    )
    assert response.status_code == 400


def test_damaged_files_are_skipped(client, tmp_path) -> None:
    directory = tmp_path / "user-subtitle-styles"
    directory.mkdir()
    (directory / "user_bad.json").write_text("{not json", encoding="utf-8")
    assert client.get("/subtitle-packs/custom").json()["items"] == []


FONT_BUNDLE = {
    "name": "宋体标题",
    "packId": "cinematic",
    "style": {"fontFamily": "song", "color": "#00ff00"},
    "animation": {"entrance": "soft_fade"},
}


def test_the_face_pick_survives_save_list_and_reapply(client) -> None:
    """Re-applying a bundle overwrites the draft style; a dropped face would
    silently reset the font the bundle was saved with."""
    created = client.post("/subtitle-packs/custom", json=FONT_BUNDLE)
    assert created.status_code == 200
    assert created.json()["style"]["fontFamily"] == "song"

    listed = client.get("/subtitle-packs/custom").json()["items"]
    assert listed[0]["style"] == {"color": "#00ff00", "fontFamily": "song"}


def test_update_replaces_or_clears_the_face(client) -> None:
    created = client.post("/subtitle-packs/custom", json=FONT_BUNDLE).json()
    updated = client.put(
        f"/subtitle-packs/custom/{created['styleId']}",
        json={**FONT_BUNDLE, "style": {"fontFamily": "kai"}},
    )
    assert updated.status_code == 200
    assert updated.json()["style"] == {"fontFamily": "kai"}

    cleared = client.put(
        f"/subtitle-packs/custom/{created['styleId']}",
        json={**FONT_BUNDLE, "style": {}},
    )
    assert cleared.json()["style"] == {}


def test_legacy_files_without_a_face_still_load(client, tmp_path) -> None:
    directory = tmp_path / "user-subtitle-styles"
    directory.mkdir()
    (directory / "user_old.json").write_text(
        json.dumps(
            {
                "style_id": "user:old",
                "name": "老风格",
                "color": "#ff0000",
            }
        ),
        encoding="utf-8",
    )
    items = client.get("/subtitle-packs/custom").json()["items"]
    assert items[0]["style"] == {"color": "#ff0000"}
