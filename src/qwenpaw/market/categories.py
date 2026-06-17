# -*- coding: utf-8 -*-
"""Category binding registry for the skill market.

Each logical category (one homepage tab) resolves per provider to either
a native filter code (modelscope today, qwenpaw once its codes are known)
or a localized search term used as fallback (clawhub / aliyun).
"""

from __future__ import annotations

from typing import Literal, TypedDict


class _Label(TypedDict):
    zh: str
    en: str


class _Category(TypedDict):
    id: str
    label: _Label
    # Native category code per provider; None = use `fallback` search.
    qwenpaw: str | None
    modelscope: str | None
    fallback: _Label


# v1: five categories aligned with ModelScope's native enum. QwenPaw
# codes stay None until the plaza publishes its category code enum.
CATEGORIES: list[_Category] = [
    {
        "id": "skill-management",
        "label": {"zh": "技能管理", "en": "Skill Mgmt"},
        "qwenpaw": None,
        "modelscope": "skill-management",
        "fallback": {"zh": "技能管理", "en": "skill management"},
    },
    {
        "id": "developer-tools",
        "label": {"zh": "开发工具", "en": "Dev Tools"},
        "qwenpaw": None,
        "modelscope": "developer-tools",
        "fallback": {"zh": "开发工具", "en": "developer tools"},
    },
    {
        "id": "ai-media",
        "label": {"zh": "AI 媒体", "en": "AI & Media"},
        "qwenpaw": None,
        "modelscope": "ai-media",
        "fallback": {"zh": "AI 媒体", "en": "ai media"},
    },
    {
        "id": "frontend-development",
        "label": {"zh": "前端", "en": "Frontend"},
        "qwenpaw": None,
        "modelscope": "frontend-development",
        "fallback": {"zh": "前端开发", "en": "frontend development"},
    },
    {
        "id": "marketing-seo",
        "label": {"zh": "营销", "en": "Marketing"},
        "qwenpaw": None,
        "modelscope": "marketing-seo",
        "fallback": {"zh": "营销", "en": "marketing seo"},
    },
]

_BY_ID: dict[str, _Category] = {c["id"]: c for c in CATEGORIES}


def _lang_key(lang: str) -> Literal["zh", "en"]:
    return "zh" if str(lang).lower().startswith("zh") else "en"


def list_categories(lang: str = "en") -> list[dict[str, str]]:
    """Return `[{id, label}]` for the category tabs, label in `lang`."""
    key = _lang_key(lang)
    return [{"id": c["id"], "label": c["label"][key]} for c in CATEGORIES]


class CategoryRouting(TypedDict):
    native_code: str | None
    search_term: str | None


def resolve(
    category_id: str | None,
    provider_key: str,
    lang: str = "en",
) -> CategoryRouting:
    """Resolve a logical category to a provider-specific action.

    - Unknown / empty category → both None (no category browse).
    - Provider has a native code → `native_code` set, `search_term` None.
    - Otherwise → `search_term` set (localized fallback), `native_code` None.
    """
    if not category_id:
        return {"native_code": None, "search_term": None}
    cat = _BY_ID.get(category_id)
    if cat is None:
        return {"native_code": None, "search_term": None}
    native = cat.get(provider_key)  # type: ignore[call-overload]
    if isinstance(native, str) and native.strip():
        return {"native_code": native, "search_term": None}
    return {
        "native_code": None,
        "search_term": cat["fallback"][_lang_key(lang)],
    }
