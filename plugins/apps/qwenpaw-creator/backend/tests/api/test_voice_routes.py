# -*- coding: utf-8 -*-
"""Character-voice HTTP surface: capability probe and direct enrollment."""
from __future__ import annotations

from api import voice_routes


def test_voice_capabilities_shape(app, run_scenario, monkeypatch):
    monkeypatch.setattr(
        voice_routes,
        "character_voice_tool_spec",
        lambda: None,
    )

    async def scenario(client):
        response = await client.get("/projects/p1/voice-capabilities")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"model", "configured", "supportsDesign"}
        assert body["configured"] is False
        assert isinstance(body["supportsDesign"], bool)

    run_scenario(app, scenario)


def test_character_voice_requires_character_ref(app, run_scenario):
    async def scenario(client):
        response = await client.post(
            "/projects/p1/character-voice",
            json={"voicePrompt": "低哑男声"},
        )
        assert response.status_code == 422

    run_scenario(app, scenario)


def test_character_voice_normalizes_ref_and_forwards(
    app,
    run_scenario,
    monkeypatch,
):
    captured: dict = {}

    async def fake_invoke(
        _services,
        *,
        project_id,
        target_ref,
        arguments,
        idempotency_key,
    ):
        captured.update(
            project_id=project_id,
            target_ref=target_ref,
            arguments=dict(arguments),
            idempotency_key=idempotency_key,
        )
        return {"ok": True, "status": "SUCCEEDED", "entityId": "hero"}

    monkeypatch.setattr(
        voice_routes,
        "invoke_character_voice_tool",
        fake_invoke,
    )

    async def scenario(client):
        response = await client.post(
            "/projects/p1/character-voice",
            json={"characterRef": "visual-entity:hero", "voicePrompt": "低哑"},
            headers={"Idempotency-Key": "voice-req-9"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    run_scenario(app, scenario)
    # 前端各种 ref 前缀（visual-entity:/裸 id）统一成执行器要求的 asset: 形态。
    assert captured["target_ref"] == "asset:hero"
    assert captured["project_id"] == "p1"
    assert captured["idempotency_key"] == "voice-req-9"
    assert captured["arguments"]["voicePrompt"] == "低哑"
