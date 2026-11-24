# -*- coding: utf-8 -*-
"""Subtitle-bar style overrides (colour / font size / outline / plate)."""

import pytest

from services.media_files import overlay
from services.media_files.motion_templates import render_caption_template
from services.media_files.overlay import (
    _find_cjk_font,
    _resolve_subtitle_font,
    _subtitle_pack_painter,
    _subtitle_style_values,
)
from services.project_files.models import ProjectSettings, SubtitleStyle


class TestSubtitleStyleValues:
    def test_missing_style_keeps_renderer_defaults(self) -> None:
        assert _subtitle_style_values(None) == ("#FFFFFF", 1.0, 1.0)
        assert _subtitle_style_values({}) == ("#FFFFFF", 1.0, 1.0)

    def test_valid_colour_is_preserved(self) -> None:
        color, _, _ = _subtitle_style_values({"color": "#ffdd00"})
        assert color == "#ffdd00"

    @pytest.mark.parametrize(
        "raw",
        ["white", "#fff", "#gggggg", "", None, 123],
    )
    def test_malformed_colour_falls_back_to_white(self, raw: object) -> None:
        color, _, _ = _subtitle_style_values({"color": raw})
        assert color == "#FFFFFF"

    def test_scales_are_clamped_to_safe_ranges(self) -> None:
        _, font, stroke = _subtitle_style_values(
            {"font_scale": 5.0, "stroke_scale": -2.0},
        )
        assert font == 1.8
        assert stroke == 0.0

        _, font, stroke = _subtitle_style_values(
            {"font_scale": 0.05, "stroke_scale": 99.0},
        )
        assert font == 0.6
        assert stroke == 3.0

    def test_zero_stroke_disables_the_outline(self) -> None:
        _, _, stroke = _subtitle_style_values({"stroke_scale": 0})
        assert stroke == 0.0

    @pytest.mark.parametrize("raw", ["big", None, float("nan")])
    def test_non_numeric_scales_keep_defaults(self, raw: object) -> None:
        _, font, stroke = _subtitle_style_values(
            {"font_scale": raw, "stroke_scale": raw},
        )
        assert font == 1.0
        assert stroke == 1.0


class TestSubtitleStyleModel:
    def test_settings_default_to_no_override(self) -> None:
        assert ProjectSettings().subtitle_style is None
        assert SubtitleStyle().background_opacity is None

    def test_style_round_trips_through_the_settings_document(self) -> None:
        settings = ProjectSettings(
            subtitle_style=SubtitleStyle(
                color="#FFE066",
                font_scale=1.25,
                stroke_scale=0.0,
            ),
        )
        restored = ProjectSettings.model_validate(
            settings.model_dump(mode="json"),
        )
        assert restored.subtitle_style is not None
        assert restored.subtitle_style.color == "#FFE066"
        assert restored.subtitle_style.font_scale == 1.25
        assert restored.subtitle_style.stroke_scale == 0.0

    def test_font_family_defaults_to_none_and_round_trips(self) -> None:
        assert SubtitleStyle().font_family is None
        settings = ProjectSettings(
            subtitle_style=SubtitleStyle(font_family="song"),
        )
        restored = ProjectSettings.model_validate(
            settings.model_dump(mode="json"),
        )
        assert restored.subtitle_style is not None
        assert restored.subtitle_style.font_family == "song"

    def test_unknown_font_family_is_rejected(self) -> None:
        with pytest.raises(Exception):
            SubtitleStyle.model_validate({"font_family": "comic-sans"})

    @pytest.mark.parametrize(
        "payload",
        [
            {"color": "red"},
            {"font_scale": 4.0},
            {"stroke_scale": -0.5},
            {"background_opacity": 1.5},
            {"background_opacity": -0.2},
        ],
    )
    def test_out_of_range_values_are_rejected(self, payload: dict) -> None:
        with pytest.raises(Exception):
            SubtitleStyle.model_validate(payload)


class TestResolveSubtitleFont:
    """A font-family id maps to an installed face, else the auto sans face."""

    def test_auto_and_unknown_ids_keep_the_auto_face(self) -> None:
        fallback = _find_cjk_font()
        assert _resolve_subtitle_font(None) == fallback
        assert _resolve_subtitle_font("default") == fallback
        assert _resolve_subtitle_font("DEFAULT") == fallback
        assert _resolve_subtitle_font("") == fallback
        assert _resolve_subtitle_font("comic-sans") == fallback

    def test_a_named_family_prefers_an_installed_face(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        present = tmp_path / "present.ttf"
        present.write_bytes(b"dummy")
        missing = str(tmp_path / "missing.ttf")
        monkeypatch.setitem(
            overlay._SUBTITLE_FONT_FAMILIES,
            "song",
            (missing, str(present)),
        )
        # Neither dummy face hugs the baseline, so the resolver settles on the
        # first candidate that exists instead of the auto face.
        monkeypatch.setattr(
            overlay,
            "_punctuation_hugs_baseline",
            lambda *args, **kwargs: False,
        )
        assert _resolve_subtitle_font("song") == str(present)

    def test_a_named_family_with_no_face_installed_falls_back(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        monkeypatch.setitem(
            overlay._SUBTITLE_FONT_FAMILIES,
            "kai",
            (str(tmp_path / "absent.ttf"),),
        )
        assert _resolve_subtitle_font("kai") == _find_cjk_font()

    def test_a_glob_candidate_matches_on_demand_asset_caches(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        # macOS caches on-demand faces (Kaiti…) under opaque asset hashes;
        # the resolver has to expand the glob instead of stat()-ing it.
        cache = tmp_path / "hash.asset" / "AssetData"
        cache.mkdir(parents=True)
        present = cache / "Kaiti.ttc"
        present.write_bytes(b"dummy")
        monkeypatch.setitem(
            overlay._SUBTITLE_FONT_FAMILIES,
            "kai",
            (str(tmp_path / "*" / "AssetData" / "Kaiti.ttc"),),
        )
        monkeypatch.setattr(
            overlay,
            "_punctuation_hugs_baseline",
            lambda *args, **kwargs: False,
        )
        assert _resolve_subtitle_font("kai") == str(present)


class TestSubtitlePlatePainter:
    """The last-resort PNG draws the same block the HTML template does.

    Both read one helper for the user's plate pick, so ``0`` means "no block"
    in the fallback cut as well, and a project that never picked anything gets
    the pack's own alpha byte for byte.
    """

    def test_the_pack_alpha_is_what_an_untouched_project_gets(self) -> None:
        assert _subtitle_pack_painter("warm_note", None)[1] == (
            255,
            248,
            232,
            128,
        )

    def test_a_pick_re_inks_the_pack_block(self) -> None:
        assert _subtitle_pack_painter(
            "warm_note",
            {"background_opacity": 0.25},
        )[1] == (255, 248, 232, 64)

    def test_zero_paints_no_block_at_all(self) -> None:
        assert (
            _subtitle_pack_painter("clean_talk", {"background_opacity": 0})[1]
            is None
        )

    @pytest.mark.parametrize("alpha", [None, 0.0, 0.5, 1.0])
    def test_a_pack_without_a_block_stays_without_one(
        self,
        alpha: float | None,
    ) -> None:
        assert (
            _subtitle_pack_painter(
                "cinematic",
                {"background_opacity": alpha},
            )[1]
            is None
        )


class TestCaptionTemplateFontFamily:
    """An explicit font pick rides into the HTML caption document."""

    def test_a_user_pick_replaces_the_pack_face(self) -> None:
        html = render_caption_template("你好", style={"font_family": "song"})
        assert '"Songti SC"' in html

    def test_no_pick_keeps_the_legacy_family(self) -> None:
        html = render_caption_template("你好")
        assert '"Songti SC"' not in html
        assert '"Noto Sans CJK SC"' in html

    @pytest.mark.parametrize("family", ["default", "comic-sans", ""])
    def test_default_and_unknown_ids_keep_the_legacy_family(
        self,
        family: str,
    ) -> None:
        html = render_caption_template("你好", style={"font_family": family})
        assert '"Songti SC"' not in html
