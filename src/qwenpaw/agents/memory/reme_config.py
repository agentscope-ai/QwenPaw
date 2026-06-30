# -*- coding: utf-8 -*-
"""Embedded ReMe application configuration for QwenPaw memory.

ReMe's standalone CLI normally loads YAML such as
``reme/config/default.yaml`` or ``reme/config/qwenpaw.yaml``.  QwenPaw embeds
ReMe as an in-process application, so it passes an equivalent configuration
dict directly to ``reme.application.Application`` / ``reme.reme.ReMe``.
"""

from copy import deepcopy
from typing import Any

from qwenpaw.config.config import AgentProfileConfig, EmbeddingModelConfig


def build_reme_app_config(
    *,
    working_dir: str,
    agent_config: AgentProfileConfig,
    user_timezone: str | None = None,
) -> dict[str, Any]:
    """Build ReMe ``Application`` kwargs for embedded QwenPaw usage."""
    reme_config = agent_config.running.reme_light_memory_config
    cfg = _base_config(reme_config.enable_search_raw_log)
    _apply_embedding_config(
        cfg,
        reme_config.embedding_model_config,
    )
    cfg.update(
        {
            "workspace_dir": working_dir,
            "metadata_dir": reme_config.metadata_dir,
            "session_dir": reme_config.session_dir,
            "resource_dir": reme_config.resource_dir,
            "daily_dir": reme_config.daily_dir,
            "digest_dir": reme_config.digest_dir,
            "language": agent_config.language,
            "timezone": user_timezone or "Asia/Shanghai",
            "enable_logo": False,
            "log_to_console": False,
        },
    )

    return cfg


def _base_config(enable_search_raw_log: bool = False) -> dict[str, Any]:
    """Return the ReMe config shape used by QwenPaw."""
    watch_dirs, watch_suffixes = _index_watch_rules(enable_search_raw_log)

    return {
        "service": {"backend": "http"},
        "jobs": {
            "index_update_loop": {
                "backend": "background",
                "watch_dirs": watch_dirs,
                "watch_suffixes": watch_suffixes,
                "steps": [
                    {
                        "backend": "init_changes_step",
                        "monitor_type": "file_store",
                        "monitor_name": "default",
                        "dispatch_steps": ["update_index_step"],
                    },
                    {
                        "backend": "watch_changes_step",
                        "dispatch_steps": [
                            {"backend": "update_index_step", "persist": False},
                        ],
                    },
                ],
            },
            "resource_watch_loop": {
                "backend": "background",
                "watch_dirs": ["resource_dir"],
                "watch_suffixes": [
                    "md",
                    "txt",
                    "json",
                    "jsonl",
                    "csv",
                    "yaml",
                    "html",
                ],
                "steps": [
                    {
                        "backend": "init_changes_step",
                        "monitor_type": "file_catalog",
                        "monitor_name": "resource",
                        "dispatch_steps": [
                            {
                                "backend": "update_catalog_step",
                                "file_catalog": "resource",
                            },
                            {"backend": "auto_resource_step"},
                        ],
                    },
                    {
                        "backend": "watch_changes_step",
                        "dispatch_steps": [
                            {
                                "backend": "update_catalog_step",
                                "file_catalog": "resource",
                            },
                            {"backend": "auto_resource_step"},
                        ],
                    },
                ],
            },
            "version": {
                "backend": "base",
                "description": "return reme package version",
                "parameters": {"type": "object", "properties": {}},
                "steps": [{"backend": "version_step"}],
            },
            "reindex": {
                "backend": "base",
                "description": (
                    "wipe the file store and rebuild it from the existing "
                    "files"
                ),
                "watch_dirs": watch_dirs,
                "watch_suffixes": watch_suffixes,
                "parameters": {"type": "object", "properties": {}},
                "steps": [
                    {"backend": "clear_store_step"},
                    {
                        "backend": "init_changes_step",
                        "monitor_type": "file_store",
                        "monitor_name": "default",
                        "dispatch_steps": ["update_index_step"],
                    },
                ],
            },
            "search": {
                "backend": "base",
                "description": (
                    "Hybrid workspace search (vector + BM25, RRF-fused)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "search query",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "max results",
                            "default": 5,
                        },
                        "min_score": {
                            "type": "number",
                            "description": "min fused score",
                            "default": 0.0,
                        },
                    },
                    "required": ["query"],
                },
                "steps": [
                    {
                        "backend": "search_step",
                        "vector_weight": 0.7,
                        "candidate_multiplier": 3.0,
                        "expand_links": True,
                        "max_links_per_direction": 10,
                    },
                ],
            },
            "node_search": {
                "backend": "base",
                "description": (
                    "Digest node recall — given a candidate abstraction's "
                    "name+description, surface existing digest nodes similar "
                    "enough to either dedup against or link to as related."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "search query",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "max digest nodes to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                "steps": [
                    {
                        "backend": "node_search_step",
                        "vector_weight": 0.7,
                        "candidate_multiplier": 5.0,
                    },
                ],
            },
            "daily_list": {
                "backend": "base",
                "description": "List notes under a single day.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "YYYY-MM-DD; empty = today",
                            "default": "",
                        },
                    },
                },
                "steps": [{"backend": "daily_list_step"}],
            },
            "daily_reindex": {
                "backend": "base",
                "description": "Rebuild the day-index page daily/<date>.md.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "YYYY-MM-DD; empty = today",
                            "default": "",
                        },
                    },
                },
                "steps": [{"backend": "daily_reindex_step"}],
            },
            "frontmatter_delete": {
                "backend": "base",
                "description": "Drop keys from a file's frontmatter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "keys": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["path", "keys"],
                },
                "steps": [{"backend": "frontmatter_delete_step"}],
            },
            "frontmatter_read": {
                "backend": "base",
                "description": "Read a file's frontmatter.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "steps": [{"backend": "frontmatter_read_step"}],
            },
            "frontmatter_update": {
                "backend": "base",
                "description": "Merge key-values into a file's frontmatter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["path", "metadata"],
                },
                "steps": [{"backend": "frontmatter_update_step"}],
            },
            "stat": {
                "backend": "base",
                "description": "Stat path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "steps": [{"backend": "stat_step"}],
            },
            "list": {
                "backend": "base",
                "description": "List files under a vault path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": ""},
                        "recursive": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "default": 100},
                    },
                },
                "steps": [{"backend": "list_step"}],
            },
            "move": {
                "backend": "base",
                "description": "Move / rename a vault file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src_path": {"type": "string"},
                        "dst_path": {"type": "string"},
                        "overwrite": {"type": "boolean", "default": False},
                        "retarget": {"type": "boolean", "default": True},
                    },
                    "required": ["src_path", "dst_path"],
                },
                "steps": [{"backend": "move_step"}],
            },
            "delete": {
                "backend": "base",
                "description": "Delete a vault file or folder.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "steps": [{"backend": "delete_step"}],
            },
            "read": {
                "backend": "base",
                "description": "Read a markdown file under the vault.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["path"],
                },
                "steps": [
                    {
                        "backend": "read_step",
                        "with_neighbors": False,
                        "max_neighbors_per_direction": 10,
                    },
                ],
            },
            "read_image": {
                "backend": "base",
                "description": "Read an image file as base64.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "steps": [
                    {"backend": "read_image_step", "max_bytes": 5242880},
                ],
            },
            "write": {
                "backend": "base",
                "description": (
                    "Write a markdown file (create or overwrite) with "
                    "name/description frontmatter."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "content": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["path", "name", "description", "content"],
                },
                "steps": [{"backend": "write_step"}],
            },
            "daily_write": {
                "backend": "base",
                "description": (
                    "Write a daily markdown note with conversation source "
                    "frontmatter."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "daily note filename stem and frontmatter name"
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": "frontmatter description",
                        },
                        "session_id": {
                            "type": "string",
                            "description": "source conversation session "
                            "identifier",
                        },
                        "content": {
                            "type": "string",
                            "description": "body",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional extra frontmatter "
                            "fields.",
                        },
                    },
                    "required": [
                        "name",
                        "description",
                        "session_id",
                        "content",
                    ],
                },
                "steps": [{"backend": "daily_write_step"}],
            },
            "edit": {
                "backend": "base",
                "description": (
                    "Find-and-replace in a markdown file (all occurrences)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string", "default": ""},
                    },
                    "required": ["path", "old", "new"],
                },
                "steps": [{"backend": "edit_step"}],
            },
            "auto_dream": {
                "backend": "base",
                "description": (
                    "Auto-dream: scan today's day-index and daily notes, "
                    "globally extract merged units/topics, integrate digest "
                    "units, write interests.yaml, and persist the dream "
                    "catalog."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "default": ""},
                        "hint": {"type": "string", "default": ""},
                        "scan_days": {"type": "integer", "default": 2},
                        "max_units": {"type": "integer", "default": 5},
                        "topic_count": {"type": "integer", "default": 3},
                        "topic_diversity_days": {
                            "type": "integer",
                            "default": 7,
                        },
                    },
                },
                "steps": [
                    {
                        "backend": "dream_extract_step",
                        "file_catalog": "dream",
                        "topic_session_id": "interests",
                        "scan_days": 2,
                        "max_units": 5,
                    },
                    {"backend": "dream_integrate_step"},
                    {
                        "backend": "dream_topics_step",
                        "topic_count": 3,
                        "topic_diversity_days": 7,
                    },
                    {"backend": "dream_finish_step", "file_catalog": "dream"},
                ],
            },
            "proactive": {
                "backend": "base",
                "description": "Expose latest user-interest topics.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "default": ""},
                        "include_content": {
                            "type": "boolean",
                            "default": True,
                        },
                    },
                },
                "steps": [{"backend": "proactive_step"}],
            },
            "auto_memory": {
                "backend": "base",
                "description": (
                    "Auto-memory: record conversation facts into a daily "
                    "note"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "session_id": {"type": "string", "default": ""},
                        "memory_hint": {"type": "string"},
                    },
                    "required": ["messages"],
                },
                "steps": [{"backend": "auto_memory_step"}],
            },
            "auto_resource": {
                "backend": "base",
                "description": (
                    "Auto-resource: interpret resource files into daily notes"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "changes": {
                            "type": "array",
                            "description": (
                                "resource change batch, each item has "
                                "path/file_path and change"
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "file_path": {"type": "string"},
                                    "change": {
                                        "type": "string",
                                        "description": "added/"
                                        "modified/deleted",
                                    },
                                },
                            },
                        },
                    },
                    "required": ["changes"],
                },
                "steps": [{"backend": "auto_resource_step"}],
            },
        },
        "components": _base_components(),
    }


def _index_watch_rules(
    enable_search_raw_log: bool,
) -> tuple[list[str], list[str]]:
    """Return directories/suffixes indexed by ReMe search jobs."""
    if enable_search_raw_log:
        return ["daily_dir", "digest_dir", "resource_dir"], ["md", "jsonl"]
    return ["daily_dir", "digest_dir"], ["md"]


def _base_components() -> dict[str, Any]:
    return {
        "tokenizer": {"default": {"backend": "regex"}},
        # The actual model object is injected by ReMeLightMemoryManager before
        # ReMe starts.  These fields exist only to satisfy ReMe's config model.
        "as_llm": {
            "default": {
                "backend": "openai",
                "model": "qwenpaw-injected",
                "stream": True,
                "context_size": 200000,
                "max_retries": 3,
                "credential": {"api_key": "", "base_url": ""},
                "parameters": {"max_tokens": 65536, "thinking_enable": False},
            },
        },
        "agent_wrapper": {
            "default": {
                "backend": "agentscope",
                "as_llm": "default",
                "permission_mode": "bypass",
                "react_config": {"max_iters": 30},
                "context_config": {
                    "trigger_ratio": 0.8,
                    "reserve_ratio": 0.1,
                    "tool_result_limit": 50000,
                },
                "model_config": {"max_retries": 1},
            },
        },
        "file_graph": {"default": {"backend": "local"}},
        "file_catalog": {
            "default": {"backend": "local"},
            "resource": {"backend": "local"},
            "digest": {"backend": "local"},
            "dream": {"backend": "local"},
        },
        "file_chunker": {
            "markdown": {
                "backend": "markdown",
                "supported_extensions": ["md"],
            },
            "default": {
                "backend": "default",
                "supported_extensions": ["jsonl"],
            },
        },
        "keyword_index": {
            "default": {"backend": "bm25", "tokenizer": "default"},
        },
        "as_embedding": {
            "default": {
                "backend": "openai",
                "model": "",
                "credential": {"api_key": "", "base_url": ""},
                "parameters": {},
            },
        },
        "embedding_store": {
            "default": {
                "backend": "local",
                "as_embedding": "default",
                "enable_cache": True,
                "max_cache_size": 3000,
                "max_input_length": 8192,
                "max_batch_size": 10,
            },
        },
        "file_store": {
            "default": {
                "backend": "local",
                "store_name": "local",
                "embedding_store": "default",
                "keyword_index": "default",
                "file_graph": "default",
            },
        },
    }


def _apply_embedding_config(
    cfg: dict[str, Any],
    embedding_config: EmbeddingModelConfig,
) -> None:
    """Map QwenPaw embedding config into ReMe component config."""
    components = cfg["components"]
    parameters: dict[str, Any] = {}
    if embedding_config.use_dimensions:
        parameters["dimensions"] = embedding_config.dimensions
    embedding_store_name = (
        "default"
        if embedding_config.base_url.strip()
        and embedding_config.model_name.strip()
        else ""
    )

    components["as_embedding"]["default"].update(
        {
            "backend": embedding_config.backend,
            "model": embedding_config.model_name,
            "credential": {
                "api_key": embedding_config.api_key,
                "base_url": embedding_config.base_url,
            },
            "parameters": parameters,
        },
    )
    components["embedding_store"]["default"].update(
        {
            "enable_cache": embedding_config.enable_cache,
            "max_cache_size": embedding_config.max_cache_size,
            "max_input_length": embedding_config.max_input_length,
            "max_batch_size": embedding_config.max_batch_size,
        },
    )
    components["file_store"]["default"][
        "embedding_store"
    ] = embedding_store_name


def get_reme_app_config(
    *,
    working_dir: str,
    agent_config: AgentProfileConfig,
    user_timezone: str | None = None,
) -> dict[str, Any]:
    """Public wrapper returning a deep copy safe for caller mutation."""
    return deepcopy(
        build_reme_app_config(
            working_dir=working_dir,
            agent_config=agent_config,
            user_timezone=user_timezone,
        ),
    )
