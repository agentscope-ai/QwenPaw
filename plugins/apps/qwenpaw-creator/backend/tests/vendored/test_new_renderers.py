# -*- coding: utf-8 -*-
"""Tests for the geo/drawio/model3d/latex renderers (WT-A3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vendor.media_toolkit.renderers import (
    SUPPORTED_EXTENSIONS,
    get_renderer,
    renderer_module_name,
)

pytestmark = pytest.mark.unit


def test_new_extensions_are_registered() -> None:
    for ext, module in (
        (".geojson", "geo"),
        (".kml", "geo"),
        (".shp", "geo"),
        (".drawio", "drawio"),
        (".obj", "model3d"),
        (".stl", "model3d"),
        (".glb", "model3d"),
        (".gltf", "model3d"),
        (".ply", "model3d"),
        (".tex", "latex"),
    ):
        assert ext in SUPPORTED_EXTENSIONS
        assert renderer_module_name(ext) == module, ext


def _blocks_by_type(blocks):
    grouped: dict[str, list] = {}
    for block in blocks:
        grouped.setdefault(block.get("type"), []).append(block)
    return grouped


def test_geo_renders_a_geojson_feature_collection(tmp_path: Path) -> None:
    pytest.importorskip("geopandas")
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "上海", "population": 24_870_000},
                "geometry": {
                    "type": "Point",
                    "coordinates": [121.47, 31.23],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "北京", "population": 21_540_000},
                "geometry": {
                    "type": "Point",
                    "coordinates": [116.40, 39.90],
                },
            },
        ],
    }
    path = tmp_path / "cities.geojson"
    path.write_text(json.dumps(payload), encoding="utf-8")

    blocks = get_renderer(".geojson")(str(path))
    grouped = _blocks_by_type(blocks)
    assert grouped["meta"][0]["format"] == "gis"
    assert grouped["image"], "GIS render must produce a map image"
    assert grouped["image"][0]["image"].size[0] > 0
    assert "2 features" in grouped["full_text"][0]["text"]


_DRAWIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile><diagram name="Flow">
  <mxGraphModel><root>
    <mxCell id="0"/><mxCell id="1" parent="0"/>
    <mxCell id="2" value="Start" style="rounded=1" vertex="1" parent="1">
      <mxGeometry x="40" y="40" width="120" height="60"/>
    </mxCell>
    <mxCell id="3" value="End" style="ellipse" vertex="1" parent="1">
      <mxGeometry x="240" y="40" width="120" height="60"/>
    </mxCell>
    <mxCell id="4" edge="1" parent="1">
      <mxGeometry x="160" y="70" width="80" height="0"/>
    </mxCell>
  </root></mxGraphModel>
</diagram></mxfile>
"""


def test_model3d_renders_canonical_views(tmp_path: Path) -> None:
    trimesh = pytest.importorskip("trimesh")
    path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(1.0, 2.0, 3.0)).export(str(path))

    blocks = get_renderer(".stl")(str(path))
    grouped = _blocks_by_type(blocks)
    assert grouped["meta"][0]["format"] == "model3d"
    assert len(grouped["image"]) == 3, "one image per canonical view"
    assert "8 vertices" in grouped["full_text"][0]["text"]
