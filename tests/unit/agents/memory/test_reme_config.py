# -*- coding: utf-8 -*-
"""Tests for embedded ReMe configuration mapping."""

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentsRunningConfig,
    EmbeddingModelConfig,
    ReMeLightMemoryConfig,
)


def _config_for_embedding(embedding: EmbeddingModelConfig) -> dict:
    agent_config = AgentProfileConfig(
        id="agent-1",
        name="Agent One",
        running=AgentsRunningConfig(
            reme_light_memory_config=ReMeLightMemoryConfig(
                embedding_model_config=embedding,
            ),
        ),
    )
    return get_reme_app_config(
        working_dir="/tmp/qwenpaw-agent",
        agent_config=agent_config,
    )


def test_memory_search_indexes_only_memory_markdown() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    job = cfg["jobs"]["index_update_loop"]
    assert job["watch_dirs"] == ["daily_dir", "digest_dir"]
    assert job["watch_suffixes"] == ["md"]


def test_reme_file_processing_is_limited_to_10_mb() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    assert (
        cfg["jobs"]["index_update_loop"]["max_file_bytes"] == 10 * 1024 * 1024
    )


def test_reindex_job_exposes_explicit_scopes() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    reindex = cfg["jobs"]["reindex"]
    assert reindex["parameters"]["properties"]["scope"] == {
        "type": "string",
        "enum": ["all", "bm25", "embedding"],
        "default": "all",
    }
    assert reindex["steps"] == [{"backend": "reindex_step"}]


def test_pending_embedding_reindex_is_forwarded_to_file_store() -> None:
    embedding = EmbeddingModelConfig(
        backend="ollama",
        model_name="nomic-embed-text",
    )
    agent_config = AgentProfileConfig(
        id="agent-1",
        name="Agent One",
        running=AgentsRunningConfig(
            reme_light_memory_config=ReMeLightMemoryConfig(
                embedding_model_config=embedding,
                needs_reindex=True,
            ),
        ),
    )

    cfg = get_reme_app_config(
        working_dir="/tmp/qwenpaw-agent",
        agent_config=agent_config,
    )

    file_store = cfg["components"]["file_store"]["default"]
    assert file_store["embedding_rebuild_required"] is True


def test_daily_paper_replaces_auto_resource_without_removing_resource_dir():
    cfg = _config_for_embedding(EmbeddingModelConfig())

    assert cfg["plugins"] == ["auto-fin", "daily-paper"]
    assert cfg["resource_dir"] == "resource"
    assert "resource_watch_loop" not in cfg["jobs"]
    assert "auto_resource" not in cfg["jobs"]
    assert "resource" not in cfg["components"]["file_catalog"]
    assert cfg["jobs"]["daily_paper"]["steps"] == [
        {"backend": "daily_paper_collect_step"},
        {"backend": "daily_paper_rank_step"},
        {"backend": "daily_paper_select_step"},
        {"backend": "daily_paper_analyze_step"},
        {
            "backend": "daily_paper_digest_step",
            "job_tools": ["search", "read"],
        },
    ]
    assert cfg["jobs"]["daily_paper_cron"] == {
        "backend": "base",
        "enable_serve": False,
        "steps": [],
    }
    assert cfg["jobs"]["auto_fin_cron"] == {
        "backend": "base",
        "enable_serve": False,
        "steps": [],
    }


def test_reme_plugins_reuse_search_job() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    assert "memory_search" not in cfg["jobs"]
    assert cfg["jobs"]["search"]["steps"][0]["backend"] == "search_step"


def test_status_job_reports_reme_memory_usage() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    assert cfg["jobs"]["status"] == {
        "backend": "base",
        "description": (
            "report memory estimates for stateful data components and "
            "process RSS"
        ),
        "parameters": {"type": "object", "properties": {}},
        "steps": [{"backend": "status_step"}],
    }


def test_graph_snapshot_job_exposes_complete_wikilink_graph() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    assert "traverse" not in cfg["jobs"]
    assert cfg["jobs"]["graph_snapshot"] == {
        "backend": "base",
        "description": (
            "Return the complete indexed wikilink "
            "graph for frontend rendering."
        ),
        "parameters": {"type": "object", "properties": {}},
        "steps": [{"backend": "graph_snapshot_step"}],
    }


def test_openai_compatible_embedding_requires_api_key() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="",
            base_url="http://localhost:1234/v1",
            model_name="local-embedding",
        ),
    )

    assert cfg["components"]["file_store"]["default"]["embedding_store"] == ""
    assert "as_embedding" not in cfg["components"]
    assert "embedding_store" not in cfg["components"]


def test_openai_compatible_embedding_keeps_base_url_credential() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="local-key",
            base_url="http://localhost:1234/v1",
            model_name="local-embedding",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    as_embedding = cfg["components"]["as_embedding"]["default"]
    assert as_embedding["backend"] == "openai"
    assert as_embedding["credential"] == {
        "api_key": "local-key",
        "base_url": "http://localhost:1234/v1",
    }
    assert as_embedding["pass_dimensions"] is False


def test_openai_compatible_embedding_can_pass_dimensions() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="local-key",
            base_url="http://localhost:1234/v1",
            model_name="local-embedding",
            dimensions=768,
            use_dimensions=True,
        ),
    )

    as_embedding = cfg["components"]["as_embedding"]["default"]
    assert as_embedding["dimensions"] == 768
    assert as_embedding["pass_dimensions"] is True


def test_openai_compatible_embedding_omits_blank_base_url() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="openai-key",
            base_url="",
            model_name="text-embedding-3-small",
        ),
    )

    assert cfg["components"]["as_embedding"]["default"]["credential"] == {
        "api_key": "openai-key",
    }


def test_gemini_embedding_uses_api_key_without_base_url() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="gemini",
            api_key="gemini-key",
            base_url="https://ignored.example",
            model_name="gemini-embedding-001",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    assert cfg["components"]["as_embedding"]["default"]["credential"] == {
        "api_key": "gemini-key",
    }
    assert (
        "pass_dimensions" not in cfg["components"]["as_embedding"]["default"]
    )


def test_gemini_embedding_without_api_key_is_disabled() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="gemini",
            api_key="",
            base_url="",
            model_name="gemini-embedding-001",
        ),
    )

    assert cfg["components"]["file_store"]["default"]["embedding_store"] == ""
    assert "as_embedding" not in cfg["components"]
    assert "embedding_store" not in cfg["components"]


def test_ollama_embedding_maps_base_url_to_host() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="ollama",
            api_key="ignored",
            base_url="http://localhost:11434",
            model_name="nomic-embed-text",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    assert cfg["components"]["as_embedding"]["default"]["credential"] == {
        "host": "http://localhost:11434",
    }


def test_embedding_health_check_timeout_is_forwarded_to_reme() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="ollama",
            model_name="nomic-embed-text",
            health_check_timeout=45,
        ),
    )

    assert (
        cfg["components"]["embedding_store"]["default"]["health_check_timeout"]
        == 45
    )


def test_ollama_embedding_without_host_still_enables_with_model() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="ollama",
            base_url="",
            model_name="nomic-embed-text",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    assert not cfg["components"]["as_embedding"]["default"]["credential"]


def test_every_embedded_backend_is_registered_in_reme() -> None:
    """Guard the embedded job/step mapping against ReMe upgrades.

    QwenPaw hands ReMe a full replacement config, and jobs resolve their
    steps when the application starts (``BaseJob._start`` ->
    ``_resolve_step``). A single stale backend name therefore keeps the
    whole long-term memory module from starting, not just one job.
    """
    from reme.enumeration import ComponentEnum
    from reme.plugin import resolve_plugin_runtime

    cfg = _config_for_embedding(EmbeddingModelConfig())
    registry = resolve_plugin_runtime(cfg).registry

    missing: list[str] = []
    for job_name, job_cfg in cfg["jobs"].items():
        for step in job_cfg.get("steps") or []:
            backends = [step.get("backend")]
            for dispatch in step.get("dispatch_steps") or []:
                if isinstance(dispatch, dict):
                    backends.append(dispatch.get("backend"))
                else:
                    backends.append(dispatch)
            for backend in backends:
                if not backend:
                    continue
                if registry.get(ComponentEnum.STEP, backend) is None:
                    missing.append(f"{job_name} -> {backend}")

    for ctype, group in cfg["components"].items():
        try:
            enum = ComponentEnum(ctype)
        except ValueError:
            continue
        for name, comp in group.items():
            backend = (comp or {}).get("backend")
            if backend and registry.get(enum, backend) is None:
                missing.append(f"{ctype}.{name} -> {backend}")

    assert not missing, missing


def test_dream_job_no_longer_renders_topics() -> None:
    """Dream and proactive topics are separate chains since ReMe 0.4.1.13."""
    cfg = _config_for_embedding(EmbeddingModelConfig())

    dream = cfg["jobs"]["auto_dream"]
    assert [s["backend"] for s in dream["steps"]] == [
        "dream_extract_step",
        "dream_integrate_step",
        "dream_finish_step",
    ]
    props = dream["parameters"]["properties"]
    assert "topic_count" not in props
    assert "topic_diversity_days" not in props
    assert "topic_session_id" not in dream["steps"][0]
    # interests.yaml belongs to the proactive chain now.
    assert "interests.yaml" not in dream["description"]


def test_proactive_jobs_match_the_reme_chain() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())
    jobs = cfg["jobs"]

    assert [s["backend"] for s in jobs["proactive_refresh"]["steps"]] == [
        "proactive_extract_step",
        "proactive_topics_step",
        "proactive_plan_step",
        "proactive_agenda_step",
        "proactive_finish_step",
    ]
    # run_action() rejects enable_serve=False jobs, and QwenPaw drives the
    # refresh itself, so both new jobs must stay servable.
    assert jobs["proactive_refresh"].get("enable_serve", True) is True
    assert jobs["proactive_feedback"].get("enable_serve", True) is True
    assert jobs["proactive_feedback"]["parameters"]["required"] == ["items"]

    read_step = jobs["proactive"]["steps"][0]
    assert read_step["backend"] == "proactive_step"
    assert read_step["delivery_cooldown_days"] == 3
    props = jobs["proactive"]["parameters"]["properties"]
    assert "include_delivered" in props
    assert "horizon_days" in props

    # The proactive chain persists its own catalog watermark.
    assert "proactive" in cfg["components"]["file_catalog"]


def test_builtin_proactive_cron_is_neutralized() -> None:
    """QwenPaw schedules proactive itself; ReMe's 18:00 cron must not run."""
    cfg = _config_for_embedding(EmbeddingModelConfig())

    cron = cfg["jobs"]["proactive_refresh_cron"]
    assert cron["enable_serve"] is False
    assert not cron["steps"]


def _config_for_proactive(**overrides) -> dict:
    agent_config = AgentProfileConfig(
        id="agent-1",
        name="Agent One",
        running=AgentsRunningConfig(
            reme_light_memory_config=ReMeLightMemoryConfig(**overrides),
        ),
    )
    return get_reme_app_config(
        working_dir="/tmp/qwenpaw-agent",
        agent_config=agent_config,
    )


def test_delivery_cooldown_reaches_every_dedupe_layer() -> None:
    """One window has to drive the reader, the writer and the ledger."""
    cfg = _config_for_proactive(proactive_delivery_cooldown_days=9)
    jobs = cfg["jobs"]

    assert jobs["proactive"]["steps"][0]["delivery_cooldown_days"] == 9
    props = jobs["proactive"]["parameters"]["properties"]
    assert props["delivery_cooldown_days"]["default"] == 9
    agenda_step = next(
        step
        for step in jobs["proactive_refresh"]["steps"]
        if step["backend"] == "proactive_agenda_step"
    )
    assert agenda_step["redelivery_cooldown_days"] == 9


def test_host_only_proactive_switches_stay_out_of_the_reme_config() -> None:
    cfg = _config_for_proactive(
        proactive_enabled=True,
        proactive_cron_enabled=True,
        proactive_cron="30 8 * * *",
        proactive_max_items=5,
    )

    # QwenPaw schedules the chain itself, so ReMe's own cron stays inert
    # even when the host-side switch is on.
    cron = cfg["jobs"]["proactive_refresh_cron"]
    assert cron["enable_serve"] is False
    assert not cron["steps"]
