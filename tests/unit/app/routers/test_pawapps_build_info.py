# -*- coding: utf-8 -*-
"""Unit tests for PawApp listing metadata contract."""
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.app.routers.pawapps import _build_app_info

CREATOR_PLUGIN_JSON = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "apps"
    / "qwenpaw-creator"
    / "plugin.json"
)


class TestBuildAppInfoCategory:
    def test_reads_category_from_meta_pawapp(self):
        info = _build_app_info(
            {
                "id": "demo-app",
                "name": "Demo",
                "version": "1.0.0",
                "description": "demo",
                "author": "test",
                "meta": {
                    "pawapp": {
                        "category": "productivity",
                        "icon": "📋",
                        "entry_page": "/apps/demo-app",
                    },
                },
            },
        )
        assert info["category"] == "productivity"

    def test_ignores_meta_root_category(self):
        info = _build_app_info(
            {
                "id": "misplaced-app",
                "name": "Misplaced",
                "version": "1.0.0",
                "meta": {
                    "category": "video-creation",
                    "pawapp": {
                        "icon": "🎬",
                        "entry_page": "/apps/misplaced-app",
                    },
                },
            },
        )
        assert info["category"] == ""

    def test_creator_plugin_json_exposes_category_under_pawapp(self):
        manifest = json.loads(CREATOR_PLUGIN_JSON.read_text(encoding="utf-8"))
        info = _build_app_info(manifest)

        assert info["id"] == "qwenpaw-creator"
        assert info["category"] == "video-creation"
        assert "category" not in (manifest.get("meta") or {})
        assert (manifest.get("meta") or {}).get("pawapp", {}).get(
            "category",
        ) == "video-creation"
