# -*- coding: utf-8 -*-
"""User-defined subtitle styles persisted to the data root.

A custom subtitle style is a named bundle of exactly what the subtitle
style window can pick: the base style pack, the colour / size / outline /
plate / face overrides and the entrance / exit / loop triple.  Applying one is
the same as moving those controls by hand, so the caption renderer never
learns about custom styles; they live as individual JSON files under
``$CREATOR_DATA_ROOT/user-subtitle-styles/``.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from pydantic import BaseModel

from services.storage_root import require_creator_data_root

_USER_STYLE_DIR_NAME = "user-subtitle-styles"
_USER_STYLE_PREFIX = "user:"


class UserSubtitleStyle(BaseModel):
    """One saved bundle; every field mirrors a style-window control."""

    style_id: str
    name: str
    description: str = ""
    pack_id: str | None = None
    color: str | None = None
    font_scale: float | None = None
    stroke_scale: float | None = None
    background_opacity: float | None = None
    font_family: str | None = None
    entrance: str | None = None
    exit: str | None = None
    loop: bool | None = None


def _style_dir() -> Path:
    root = require_creator_data_root()
    directory = root / _USER_STYLE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _style_path(style_id: str) -> Path:
    safe_name = style_id.replace(":", "_")
    return _style_dir() / f"{safe_name}.json"


def _generate_id() -> str:
    return f"{_USER_STYLE_PREFIX}{uuid.uuid4().hex[:8]}"


def save_user_subtitle_style(
    style: UserSubtitleStyle,
) -> UserSubtitleStyle:
    path = _style_path(style.style_id)
    path.write_text(style.model_dump_json(indent=2), encoding="utf-8")
    return style


def load_user_subtitle_style(style_id: str) -> UserSubtitleStyle | None:
    path = _style_path(style_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return UserSubtitleStyle.model_validate(data)


def list_user_subtitle_styles() -> list[UserSubtitleStyle]:
    directory = _style_dir()
    styles: list[UserSubtitleStyle] = []
    for path in sorted(directory.glob("user_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            styles.append(UserSubtitleStyle.model_validate(data))
        except (json.JSONDecodeError, ValueError):
            continue
    return styles


def delete_user_subtitle_style(style_id: str) -> bool:
    path = _style_path(style_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def new_user_subtitle_style_id() -> str:
    return _generate_id()
