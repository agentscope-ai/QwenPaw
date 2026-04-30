# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...config.config import load_agent_config
from .paths import knowledge_base_root, knowledge_conf_path, knowledge_secret_path


DEFAULT_CHUNK_CONFIG = {
    "mode": "general",
    "granularity": "balanced",
    "separator": "\\n\\n",
    "normalize_whitespace": False,
    "llm_grouping": False,
    "chunk_size": 1024,
    "chunk_overlap": 50,
    "parent_separator": "\\n\\n",
    "parent_normalize_whitespace": False,
    "parent_chunk_size": 1600,
    "parent_chunk_overlap": 160,
    "child_separator": "\\n",
    "child_normalize_whitespace": False,
    "child_chunk_size": 400,
    "child_chunk_overlap": 40,
}

DEFAULT_RETRIEVAL_CONFIG = {
    "indexing_technique": "high_quality",
    "search_method": "hybrid",
    "top_k": 3,
    "score_threshold_enabled": False,
    "score_threshold": 0.35,
    "reranking_enable": False,
    "weights": {
        "vector_weight": 0.7,
        "keyword_weight": 0.3,
    },
}

DEFAULT_EMBEDDING_MODEL_CONFIG = {
    "backend": "custom",
    "base_url": "",
    "model_name": "",
    "dimensions": 1536,
    "enable_cache": True,
    "use_dimensions": True,
    "max_cache_size": 1000,
    "max_input_length": 8192,
    "max_batch_size": 16,
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read knowledge config: {exc}") from exc


def _seed_from_agent_config(agent_id: str) -> dict[str, Any]:
    try:
        config = load_agent_config(agent_id)
    except Exception:
        return DEFAULT_EMBEDDING_MODEL_CONFIG.copy()

    embedding_model_config = getattr(
        getattr(getattr(config, "running", None), "reme_light_memory_config", None),
        "embedding_model_config",
        None,
    )
    if embedding_model_config is None:
        return DEFAULT_EMBEDDING_MODEL_CONFIG.copy()

    raw = embedding_model_config.model_dump()
    return {
        **DEFAULT_EMBEDDING_MODEL_CONFIG,
        "backend": raw.get("backend") or raw.get("api_type") or "custom",
        "base_url": str(raw.get("base_url") or "").strip(),
        "model_name": str(raw.get("model_name") or "").strip(),
        "dimensions": int(raw.get("dimensions") or DEFAULT_EMBEDDING_MODEL_CONFIG["dimensions"]),
        "enable_cache": bool(raw.get("enable_cache", True)),
        "use_dimensions": bool(raw.get("use_dimensions", True)),
        "max_cache_size": int(raw.get("max_cache_size") or DEFAULT_EMBEDDING_MODEL_CONFIG["max_cache_size"]),
        "max_input_length": int(raw.get("max_input_length") or DEFAULT_EMBEDDING_MODEL_CONFIG["max_input_length"]),
        "max_batch_size": int(raw.get("max_batch_size") or DEFAULT_EMBEDDING_MODEL_CONFIG["max_batch_size"]),
    }


def normalize_embedding_model_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_EMBEDDING_MODEL_CONFIG, **(payload or {})}
    return {
        "backend": str(data.get("backend") or "custom").strip() or "custom",
        "base_url": str(data.get("base_url") or "").strip(),
        "model_name": str(data.get("model_name") or "").strip(),
        "dimensions": max(1, int(data.get("dimensions") or DEFAULT_EMBEDDING_MODEL_CONFIG["dimensions"])),
        "enable_cache": bool(data.get("enable_cache", True)),
        "use_dimensions": bool(data.get("use_dimensions", True)),
        "max_cache_size": max(1, int(data.get("max_cache_size") or DEFAULT_EMBEDDING_MODEL_CONFIG["max_cache_size"])),
        "max_input_length": max(1, int(data.get("max_input_length") or DEFAULT_EMBEDDING_MODEL_CONFIG["max_input_length"])),
        "max_batch_size": max(1, int(data.get("max_batch_size") or DEFAULT_EMBEDDING_MODEL_CONFIG["max_batch_size"])),
    }


def normalize_retrieval_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = {**DEFAULT_RETRIEVAL_CONFIG, **(payload or {})}
    weights = {
        **DEFAULT_RETRIEVAL_CONFIG["weights"],
        **((data.get("weights") or {}) if isinstance(data.get("weights"), dict) else {}),
    }
    indexing_technique = str(data.get("indexing_technique") or "high_quality").strip()
    if indexing_technique not in {"high_quality", "economy"}:
        indexing_technique = "high_quality"

    search_method = str(data.get("search_method") or "hybrid").strip()
    allowed_methods = {"semantic", "full_text", "hybrid"} if indexing_technique == "high_quality" else {"keyword"}
    if search_method not in allowed_methods:
        search_method = "hybrid" if indexing_technique == "high_quality" else "keyword"

    vector_weight = float(weights.get("vector_weight") or DEFAULT_RETRIEVAL_CONFIG["weights"]["vector_weight"])
    keyword_weight = float(weights.get("keyword_weight") or DEFAULT_RETRIEVAL_CONFIG["weights"]["keyword_weight"])
    total = vector_weight + keyword_weight
    if total <= 0:
        vector_weight, keyword_weight = 0.7, 0.3
        total = 1.0

    return {
        "indexing_technique": indexing_technique,
        "search_method": search_method,
        "top_k": max(1, int(data.get("top_k") or DEFAULT_RETRIEVAL_CONFIG["top_k"])),
        "score_threshold_enabled": bool(data.get("score_threshold_enabled", False)),
        "score_threshold": min(1.0, max(0.0, float(data.get("score_threshold") or 0.0))),
        "reranking_enable": bool(data.get("reranking_enable", False)),
        "weights": {
            "vector_weight": vector_weight / total,
            "keyword_weight": keyword_weight / total,
        },
    }


def normalize_chunk_config(
    payload: dict[str, Any] | None,
    indexing_technique: str = "high_quality",
) -> dict[str, Any]:
    data = {**DEFAULT_CHUNK_CONFIG, **(payload or {})}
    mode = str(data.get("mode") or "general").strip()
    if mode not in {"general", "parent_child"}:
        mode = "general"
    if indexing_technique != "high_quality":
        mode = "general"

    granularity = str(data.get("granularity") or "balanced").strip()
    if granularity not in {"balanced", "paragraph", "sentence"}:
        granularity = "balanced"

    return {
        "mode": mode,
        "granularity": granularity,
        "separator": str(
            data.get("separator")
            if data.get("separator") is not None
            else DEFAULT_CHUNK_CONFIG["separator"]
        ),
        "normalize_whitespace": bool(data.get("normalize_whitespace", DEFAULT_CHUNK_CONFIG["normalize_whitespace"])),
        "llm_grouping": bool(data.get("llm_grouping", DEFAULT_CHUNK_CONFIG["llm_grouping"])),
        "chunk_size": max(100, int(data.get("chunk_size") or DEFAULT_CHUNK_CONFIG["chunk_size"])),
        "chunk_overlap": max(0, int(data.get("chunk_overlap") or DEFAULT_CHUNK_CONFIG["chunk_overlap"])),
        "parent_separator": str(
            data.get("parent_separator")
            if data.get("parent_separator") is not None
            else DEFAULT_CHUNK_CONFIG["parent_separator"]
        ),
        "parent_normalize_whitespace": bool(
            data.get("parent_normalize_whitespace", DEFAULT_CHUNK_CONFIG["parent_normalize_whitespace"])
        ),
        "parent_chunk_size": max(100, int(data.get("parent_chunk_size") or DEFAULT_CHUNK_CONFIG["parent_chunk_size"])),
        "parent_chunk_overlap": max(0, int(data.get("parent_chunk_overlap") or DEFAULT_CHUNK_CONFIG["parent_chunk_overlap"])),
        "child_separator": str(
            data.get("child_separator")
            if data.get("child_separator") is not None
            else DEFAULT_CHUNK_CONFIG["child_separator"]
        ),
        "child_normalize_whitespace": bool(
            data.get("child_normalize_whitespace", DEFAULT_CHUNK_CONFIG["child_normalize_whitespace"])
        ),
        "child_chunk_size": max(100, int(data.get("child_chunk_size") or DEFAULT_CHUNK_CONFIG["child_chunk_size"])),
        "child_chunk_overlap": max(0, int(data.get("child_chunk_overlap") or DEFAULT_CHUNK_CONFIG["child_chunk_overlap"])),
    }


def ensure_knowledge_conf(agent_id: str) -> None:
    root = knowledge_base_root()
    root.mkdir(parents=True, exist_ok=True)
    conf_path = knowledge_conf_path()
    if conf_path.exists():
        return
    seeded = {
        "embedding_model_config": _seed_from_agent_config(agent_id),
        "default_chunk_config": DEFAULT_CHUNK_CONFIG,
        "retrieval_config": DEFAULT_RETRIEVAL_CONFIG,
    }
    conf_path.write_text(json.dumps(seeded, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        config = load_agent_config(agent_id)
        api_key = str(
            getattr(
                getattr(getattr(config, "running", None), "reme_light_memory_config", None),
                "embedding_model_config",
                None,
            ).api_key
            or ""
        ).strip()
    except Exception:
        api_key = ""
    if api_key:
        secret_path = knowledge_secret_path()
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        if not secret_path.exists():
            secret_path.write_text(api_key, encoding="utf-8")


def load_knowledge_vector_config(agent_id: str, include_secret: bool = False) -> dict[str, Any]:
    ensure_knowledge_conf(agent_id)
    conf_data = _read_json(knowledge_conf_path())
    embedding_model_config = normalize_embedding_model_config(conf_data.get("embedding_model_config"))
    retrieval_config = normalize_retrieval_config(conf_data.get("retrieval_config"))
    secret_path = knowledge_secret_path()
    try:
        api_key = secret_path.read_text(encoding="utf-8").strip() if secret_path.exists() else ""
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read knowledge API key: {exc}") from exc

    return {
        "embedding_model_config": {
            **embedding_model_config,
            "api_key": api_key if include_secret else "",
            "api_key_configured": bool(api_key),
        },
        "default_chunk_config": normalize_chunk_config(
            conf_data.get("default_chunk_config"),
            retrieval_config["indexing_technique"],
        ),
        "retrieval_config": retrieval_config,
    }


def save_knowledge_vector_config(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_knowledge_conf(agent_id)
    vector_config = normalize_embedding_model_config((payload.get("embedding_model_config") or {}))
    secret_path = knowledge_secret_path()
    try:
        existing_api_key = secret_path.read_text(encoding="utf-8").strip() if secret_path.exists() else ""
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read knowledge API key: {exc}") from exc

    api_key = str((payload.get("embedding_model_config") or {}).get("api_key") or "").strip()
    if not api_key:
        api_key = existing_api_key

    retrieval_config = normalize_retrieval_config(payload.get("retrieval_config"))
    conf_payload = {
        "embedding_model_config": vector_config,
        "default_chunk_config": normalize_chunk_config(
            payload.get("default_chunk_config"),
            retrieval_config["indexing_technique"],
        ),
        "retrieval_config": retrieval_config,
    }
    knowledge_conf_path().write_text(
        json.dumps(conf_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(api_key, encoding="utf-8")
    return load_knowledge_vector_config(agent_id)


def get_vector_model_summary(agent_id: str) -> dict[str, Any]:
    config = load_knowledge_vector_config(agent_id)["embedding_model_config"]
    base_url = str(config.get("base_url") or "").strip()
    model_name = str(config.get("model_name") or "").strip()
    return {
        "available": bool(base_url and model_name),
        "provider": str(config.get("backend") or "custom"),
        "base_url": base_url,
        "model_name": model_name,
        "dimensions": config.get("dimensions"),
    }


def get_upload_capabilities(agent_id: str) -> dict[str, Any]:
    from .parsing import SUPPORTED_UPLOAD_SUFFIXES

    vector_model = get_vector_model_summary(agent_id)
    conf = load_knowledge_vector_config(agent_id)
    retrieval_config = conf["retrieval_config"]
    requires_embedding = retrieval_config["indexing_technique"] == "high_quality"
    return {
        "supported_extensions": sorted(SUPPORTED_UPLOAD_SUFFIXES),
        "default_chunk_config": conf["default_chunk_config"],
        "retrieval_config": retrieval_config,
        "vector_model": vector_model,
        "requires_embedding": requires_embedding,
        "can_upload": bool(vector_model["available"]) if requires_embedding else True,
    }