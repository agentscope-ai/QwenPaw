# -*- coding: utf-8 -*-
"""OMP loop UI i18n catalog and CommandSpec metadata wiring."""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_I18N_PATH = (
    _REPO
    / "plugins"
    / "bundle"
    / "omp_workflows"
    / "shared"
    / "loop_ui_i18n.py"
)


@lru_cache(maxsize=1)
def _omp_loop_ui_i18n():
    spec = importlib.util.spec_from_file_location(
        "omp_loop_ui_i18n",
        _I18N_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "mode_key",
    ["ultrawork", "ralph", "autopilot", "ultraqa", "team"],
)
def test_loop_ui_has_en_and_zh_description(mode_key: str):
    mod = _omp_loop_ui_i18n()
    ui = mod.loop_ui(mode_key)
    assert ui["description"]["en"]
    assert ui["description"]["zh-CN"]
    assert ui["name"]["en"]
    assert mod.loop_help_text(mode_key).startswith("**")


def test_loop_command_metadata_exposes_i18n_maps():
    meta = _omp_loop_ui_i18n().loop_command_metadata("ultrawork")
    assert meta["loop_name"] == "Ultrawork"
    assert "zh-CN" in meta["description_i18n"]
    assert "en" in meta["name_i18n"]


def test_as_str_dict_and_catalog_fields():
    from qwenpaw.app.routers.loops import LoopModeInfo, _as_str_dict

    assert _as_str_dict({"en": "Hi", "zh-CN": "你好"}) == {
        "en": "Hi",
        "zh-CN": "你好",
    }
    assert not _as_str_dict("nope")

    info = LoopModeInfo(
        id="plugin:ultrawork",
        name="Ultrawork",
        slash_command="ultrawork",
        description="help",
        source="plugin",
        name_i18n={"en": "Ultrawork"},
        description_i18n={"zh-CN": "**Ultrawork** — 并行"},
    )
    desc_i18n = info.description_i18n or {}
    assert desc_i18n["zh-CN"].startswith("**Ultrawork**")
