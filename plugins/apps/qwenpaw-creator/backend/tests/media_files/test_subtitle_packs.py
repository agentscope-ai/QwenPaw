"""Subtitle style packs (JianYing-like) bias the caption fallback chain."""

from services.media_files.motion_blueprints import (
    CAPTION_BLUEPRINTS,
    SUBTITLE_TEMPLATE_PACKS,
    SUBTITLE_TEMPLATE_PACK_ORDER,
    blueprint_catalog_text,
    content_type_caption_order,
    subtitle_pack_caption_order,
    subtitle_pack_preview_specs,
)
from services.media_files.motion_templates import CAPTION_ENTRANCES
from services.project_files.models import ProjectSettings


class TestSubtitlePacks:
    def test_every_pack_blueprint_is_registered(self) -> None:
        for pack_id in SUBTITLE_TEMPLATE_PACK_ORDER:
            order = subtitle_pack_caption_order(pack_id)
            assert order, pack_id
            for blueprint in order:
                assert blueprint in CAPTION_BLUEPRINTS

    def test_unknown_or_empty_pack_falls_back_to_none(self) -> None:
        assert subtitle_pack_caption_order(None) is None
        assert subtitle_pack_caption_order("") is None
        assert subtitle_pack_caption_order("nope") is None

    def test_pack_overrides_content_type_order(self) -> None:
        baseline = content_type_caption_order("travel")
        packed = content_type_caption_order("travel", "cinematic")
        assert packed == subtitle_pack_caption_order("cinematic")
        assert packed != baseline

    def test_no_pack_keeps_content_type_order(self) -> None:
        assert content_type_caption_order(
            "travel",
        ) == content_type_caption_order(
            "travel",
            None,
        )

    def test_catalog_text_follows_pack_for_captions(self) -> None:
        text = blueprint_catalog_text(
            "caption",
            subtitle_template="clean_talk",
        )
        assert text.splitlines()[0].startswith("- static_capsule")
        # Decoration catalogs are unaffected by the caption pack.
        decor = blueprint_catalog_text(
            "decoration",
            subtitle_template="clean_talk",
        )
        assert "- static_capsule" not in decor


class TestSettingsPersistence:
    def test_default_is_smart_recommend(self) -> None:
        assert ProjectSettings().subtitle_template is None

    def test_pack_id_round_trips(self) -> None:
        settings = ProjectSettings(subtitle_template="variety_pop")
        restored = ProjectSettings.model_validate(settings.model_dump())
        assert restored.subtitle_template == "variety_pop"

    def test_packs_exposed_for_ui(self) -> None:
        assert set(SUBTITLE_TEMPLATE_PACKS) == set(
            SUBTITLE_TEMPLATE_PACK_ORDER,
        )


class TestPreviewSpecs:
    """The style-window cards preview the renderer, so specs == the table."""

    def test_specs_lead_with_smart_card_then_pack_order(self) -> None:
        specs = subtitle_pack_preview_specs()
        assert specs[0]["id"] is None
        assert [s["id"] for s in specs[1:]] == list(
            SUBTITLE_TEMPLATE_PACK_ORDER,
        )

    def test_spec_fields_mirror_pack_table(self) -> None:
        specs = {
            s["id"]: s for s in subtitle_pack_preview_specs() if s["id"]
        }
        for pack_id, pack in SUBTITLE_TEMPLATE_PACKS.items():
            spec = specs[pack_id]
            typo = pack["typography"]
            anim = pack["animation"]
            assert spec["plate"] == typo.get("plate", "")
            assert spec["plateRadius"] == typo.get("plateRadius", "0.28em")
            assert spec["glow"] == bool(typo.get("glow", False))
            assert spec["entrance"] == anim["entrance"]
            assert spec["loop"] == anim["loop"]
            assert spec["strokeScale"] == typo["strokeScale"]
            assert spec["letterSpacing"] == typo["letterSpacing"]
            # The UI pastes fontFamily into a style attribute: single
            # quotes only, and the family list itself unchanged.
            family = str(spec["fontFamily"])
            assert '"' not in family
            assert family.replace("'", '"') == typo["fontFamily"]

    def test_every_entrance_is_renderer_known(self) -> None:
        for spec in subtitle_pack_preview_specs():
            assert spec["entrance"] in CAPTION_ENTRANCES

    def test_preview_route_returns_every_pack(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.file_media_routes import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.get("/subtitle-packs/preview")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == len(SUBTITLE_TEMPLATE_PACK_ORDER) + 1
        assert items[0]["id"] is None
        assert {i["id"] for i in items[1:]} == set(
            SUBTITLE_TEMPLATE_PACK_ORDER,
        )
