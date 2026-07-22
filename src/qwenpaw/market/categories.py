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


CATEGORIES: list[_Category] = [
    {
        "id": "app",
        "label": {"zh": "应用", "en": "Apps"},
        "qwenpaw": "app",
        "modelscope": None,
        "fallback": {"zh": "应用 PawApp", "en": "app PawApp"},
    },
    {
        "id": "engineering-development",
        "label": {"zh": "工程开发", "en": "Engineering"},
        "qwenpaw": "engineering development",
        "modelscope": "developer-tools",
        "fallback": {"zh": "工程开发", "en": "engineering development"},
    },
    {
        "id": "data-research",
        "label": {"zh": "数据研究", "en": "Data & Research"},
        "qwenpaw": "data research",
        "modelscope": None,
        "fallback": {"zh": "数据研究", "en": "data research"},
    },
    {
        "id": "document-office",
        "label": {"zh": "文档办公", "en": "Docs & Office"},
        "qwenpaw": "document office",
        "modelscope": None,
        "fallback": {"zh": "文档办公", "en": "document office"},
    },
    {
        "id": "design-creation",
        "label": {"zh": "设计创作", "en": "Design"},
        "qwenpaw": "design creation",
        "modelscope": None,
        "fallback": {"zh": "设计创作", "en": "design creation"},
    },
    {
        "id": "automation-integration",
        "label": {"zh": "自动化集成", "en": "Automation"},
        "qwenpaw": "automation integration",
        "modelscope": None,
        "fallback": {"zh": "自动化集成", "en": "automation integration"},
    },
    {
        "id": "product-management",
        "label": {"zh": "产品管理", "en": "Product"},
        "qwenpaw": "product management",
        "modelscope": None,
        "fallback": {"zh": "产品管理", "en": "product management"},
    },
    {
        "id": "marketing-growth",
        "label": {"zh": "营销增长", "en": "Marketing"},
        "qwenpaw": "marketing growth",
        "modelscope": "marketing-seo",
        "fallback": {"zh": "营销增长", "en": "marketing growth"},
    },
    {
        "id": "security-compliance",
        "label": {"zh": "安全合规", "en": "Security"},
        "qwenpaw": "security compliance",
        "modelscope": None,
        "fallback": {"zh": "安全合规", "en": "security compliance"},
    },
    {
        "id": "education-knowledge",
        "label": {"zh": "教育知识", "en": "Education"},
        "qwenpaw": "education knowledge",
        "modelscope": None,
        "fallback": {"zh": "教育知识", "en": "education knowledge"},
    },
    {
        "id": "plugin-development",
        "label": {"zh": "Plugin 开发", "en": "Plugin Dev"},
        "qwenpaw": "plugin development",
        "modelscope": None,
        "fallback": {"zh": "Plugin 开发", "en": "plugin development"},
    },
    {
        "id": "skills-management",
        "label": {"zh": "Skills 管理", "en": "Skills"},
        "qwenpaw": "skills management",
        "modelscope": "skill-management",
        "fallback": {"zh": "Skills 管理", "en": "skills management"},
    },
    {
        "id": "others",
        "label": {"zh": "其它", "en": "Others"},
        "qwenpaw": "others",
        "modelscope": "other",
        "fallback": {"zh": "其它", "en": "others"},
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
