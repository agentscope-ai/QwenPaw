# -*- coding: utf-8 -*-
"""Tests for config model validators and the legacy-to-multi-agent migration.

``test_config_migration_helpers.py`` pins ``_migrate_access_control_fields``
and ``_sanitize_custom_loop_modes``; ``test_config_utils_runtime_paths.py``
pins the WORKING_DIR-bound path helpers. This file covers what neither
reaches: the one-shot ``weixin`` -> ``wechat`` key rename, the CSS color and
radius allowlists, the trusted-proxy deny list, the deprecated browser
identity knobs, the MCP field aliases, the loop-mode uniqueness gates, the
plugin-manifest tool merge, and ``migrate_legacy_config_to_multi_agent`` --
the function that turns a pre-multi-agent ``config.json`` plus a legacy
``~/.copaw`` tree into a workspace-owned ``agent.json``.
"""
# Pytest fixtures intentionally provide setup-only arguments to tests.
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=too-many-arguments,too-many-locals,too-many-branches
# C1803 is disabled because `== {}` is the assertion being made: `not tools`
# would also accept None, which is a different (and weaker) claim. Same
# convention as the other upstream config tests.
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qwenpaw.config import config as cfg_mod
from qwenpaw.config import utils as config_utils
from qwenpaw.exceptions import ConfigurationException

LEGACY_DIR = Path("~/.copaw").expanduser()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_working_dir(tmp_path: Path, monkeypatch):
    """Point config persistence, WORKING_DIR and ``~`` at one temp tree.

    ``migrate_legacy_config_to_multi_agent`` derives its target workspace
    from the module-level ``WORKING_DIR`` and reads legacy data from
    ``~/.copaw``, so both must be redirected together or the test would
    create a workspace inside the real agent working directory.
    """
    wd = tmp_path / "wd"
    wd.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    config_path = wd / "config.json"

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(cfg_mod, "WORKING_DIR", wd)
    monkeypatch.setattr(config_utils, "get_config_path", lambda: config_path)
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)
    return wd, home, config_path


def _seed_config(config_path: Path, config: cfg_mod.Config) -> None:
    """Persist *config* and drop the module cache so it is re-read."""
    config_utils.save_config(config, config_path)
    config_utils._config_cache = None
    config_utils._config_mtime = None


# ---------------------------------------------------------------------------
# _is_safe_css_color
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["#abc", "#abcd", "#aabbcc", "#aabbccdd", "  #ABC  ", "rgb(1,2,3)"],
)
def test_safe_css_color_accepts_hex_and_comma_rgb(value: str) -> None:
    assert cfg_mod._is_safe_css_color(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "rgb(1 2 3)",
        "rgba(1 2 3 / 0.5)",
        "hsl(120,50%,50%)",
        "hsla(120 50% 50% / 50%)",
    ],
)
def test_safe_css_color_accepts_space_and_slash_forms(value: str) -> None:
    assert cfg_mod._is_safe_css_color(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "url(x)",
        "rgb(1 2)",
        "rgb(1,2,3,4,5)",
        "rgb(1,2,,4)",
        "rgb(1 2 3 / 0.5 / 0.2)",
        "rgb(1,2,3,abc)",
        "hsl(a,b%,c%)",
        "",
    ],
)
def test_safe_css_color_rejects_unsupported_values(value: str) -> None:
    assert cfg_mod._is_safe_css_color(value) is False


def test_safe_css_color_hue_accepts_angle_units() -> None:
    assert cfg_mod._is_safe_css_color("hsl(120deg,50%,50%)") is True
    assert cfg_mod._is_safe_css_color("hsl(1turn,50%,50%)") is True


def test_theme_configs_strip_colors_and_reject_others() -> None:
    assert cfg_mod.ThemeConfig(accent=" #ABC ").accent == "#ABC"
    assert cfg_mod.ThemeDarkConfig(surface="#abc").surface == "#abc"
    with pytest.raises(ValidationError):
        cfg_mod.ThemeConfig(accent="javascript:alert(1)")
    with pytest.raises(ValidationError):
        cfg_mod.ThemeDarkConfig(surface="red")


def test_theme_config_radius_accepts_pixels_and_zero_only() -> None:
    assert cfg_mod.ThemeConfig(radius=" 12px ").radius == "12px"
    assert cfg_mod.ThemeConfig(radius="0").radius == "0"
    assert cfg_mod.ThemeConfig(radius=None).radius is None
    for bad in ("12", "px", "-1px", "12em"):
        with pytest.raises(ValidationError):
            cfg_mod.ThemeConfig(radius=bad)


# ---------------------------------------------------------------------------
# ChannelConfig._migrate_legacy_weixin_key
# ---------------------------------------------------------------------------


def test_legacy_weixin_key_is_renamed_to_wechat() -> None:
    channels = cfg_mod.ChannelConfig.model_validate(
        {"weixin": {"enabled": True}},
    )
    assert channels.wechat.enabled is True


def test_legacy_weixin_key_yields_to_an_explicit_wechat_entry() -> None:
    channels = cfg_mod.ChannelConfig.model_validate(
        {"weixin": {"enabled": True}, "wechat": {"enabled": False}},
    )
    assert channels.wechat.enabled is False


def test_weixin_migration_passes_non_mapping_input_through() -> None:
    payload = ["not", "a", "mapping"]
    assert cfg_mod.ChannelConfig._migrate_legacy_weixin_key(payload) is payload


# ---------------------------------------------------------------------------
# FeishuConfig._check_domain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "domain",
    ["feishu", "lark", "http://gw.example", "https://gw.example"],
)
def test_feishu_domain_accepts_known_and_url_forms(domain: str) -> None:
    assert cfg_mod.FeishuConfig(domain=domain).domain == domain


def test_feishu_domain_rejects_a_bare_third_party_host() -> None:
    with pytest.raises(ValidationError):
        cfg_mod.FeishuConfig(domain="slack.com")


# ---------------------------------------------------------------------------
# CustomLoopModeConfig / LoopConfig uniqueness gates
# ---------------------------------------------------------------------------


def _gate(gate_id: str, gate_type: str = "budget") -> dict:
    return {"id": gate_id, "type": gate_type}


def _mode(
    mode_id: str = "a",
    name: str = "A",
    slash: str = "a",
    gates: Any = None,
    enabled: bool = False,
) -> dict:
    return {
        "id": mode_id,
        "name": name,
        "slash_command": slash,
        "enabled": enabled,
        "gates": gates if gates is not None else [],
    }


def test_custom_mode_display_name_is_stripped_before_validation() -> None:
    mode = cfg_mod.CustomLoopModeConfig.model_validate(
        _mode(name="  Padded  "),
    )
    assert mode.name == "Padded"


def test_custom_mode_display_name_validator_keeps_non_strings() -> None:
    assert cfg_mod.CustomLoopModeConfig.strip_display_name(7) == 7


def test_enabled_custom_mode_requires_an_enabled_gate() -> None:
    with pytest.raises(ValidationError, match="require an enabled gate"):
        cfg_mod.CustomLoopModeConfig.model_validate(_mode(enabled=True))
    disabled = _mode(enabled=True, gates=[dict(_gate("g"), enabled=False)])
    with pytest.raises(ValidationError, match="require an enabled gate"):
        cfg_mod.CustomLoopModeConfig.model_validate(disabled)


def test_custom_mode_gate_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="IDs must be unique"):
        cfg_mod.CustomLoopModeConfig.model_validate(
            _mode(gates=[_gate("g", "budget"), _gate("g", "token")]),
        )


def test_custom_mode_enabled_gate_types_cannot_repeat() -> None:
    with pytest.raises(ValidationError, match="cannot be repeated"):
        cfg_mod.CustomLoopModeConfig.model_validate(
            _mode(gates=[_gate("g1", "budget"), _gate("g2", "budget")]),
        )


def test_loop_config_rejects_duplicate_mode_ids() -> None:
    with pytest.raises(ValidationError, match="IDs must be unique"):
        cfg_mod.LoopConfig(
            custom_modes=[_mode("a"), _mode("a", name="B", slash="b")],
        )


def test_loop_config_rejects_duplicate_slash_commands() -> None:
    with pytest.raises(ValidationError, match="slash commands must be unique"):
        cfg_mod.LoopConfig(
            custom_modes=[_mode("a", slash="x"), _mode("b", slash="x")],
        )


def test_loop_config_rejects_duplicate_mode_names() -> None:
    # ids and slash commands must differ, or an earlier gate fires first and
    # the name check is never reached.
    with pytest.raises(ValidationError, match="names must be unique"):
        cfg_mod.LoopConfig(
            custom_modes=[
                _mode("a", name="Same", slash="one"),
                _mode("b", name=" same ", slash="two"),
            ],
        )


# ---------------------------------------------------------------------------
# _sanitize_loop_config
# ---------------------------------------------------------------------------


def test_sanitize_loop_replaces_a_non_mapping_loop_with_defaults() -> None:
    data: dict = {"running": {"loop": "not-a-mapping"}}
    cfg_mod._sanitize_loop_config(data, "agent-a")
    assert isinstance(data["running"]["loop"], dict)
    assert "custom_modes" in data["running"]["loop"]


def test_sanitize_loop_leaves_other_shapes_untouched() -> None:
    for data in ({"running": "x"}, {"running": {}}, {}):
        original = json.loads(json.dumps(data))
        cfg_mod._sanitize_loop_config(data, "agent-a")
        assert data == original


def test_sanitize_loop_drops_an_unparseable_loop_payload() -> None:
    data: dict = {"running": {"loop": {"max_iterations": "abc"}}}
    cfg_mod._sanitize_loop_config(data, "agent-a")
    assert "max_iterations" not in data["running"]["loop"]


# ---------------------------------------------------------------------------
# AgentsRunningConfig memory backend normalization
# ---------------------------------------------------------------------------


def test_memory_backend_id_is_lowercased_and_stripped() -> None:
    cfg = cfg_mod.AgentsRunningConfig(memory_manager_backend="  RemeLight ")
    assert cfg.memory_manager_backend == "remelight"


def test_blank_memory_backend_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        cfg_mod.AgentsRunningConfig(memory_manager_backend="   ")


def test_memory_backend_config_ids_are_canonicalized() -> None:
    cfg = cfg_mod.AgentsRunningConfig(memory_backend_configs={" A ": {"k": 1}})
    assert cfg.memory_backend_configs == {"a": {"k": 1}}


def test_blank_memory_backend_config_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        cfg_mod.AgentsRunningConfig(memory_backend_configs={"  ": {}})


def test_ambiguous_memory_backend_config_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        cfg_mod.AgentsRunningConfig(
            memory_backend_configs={"A": {}, "a": {}},
        )


# ---------------------------------------------------------------------------
# MCPClientConfig alias normalization and transport validation
# ---------------------------------------------------------------------------


def test_mcp_aliases_are_normalized_onto_canonical_fields() -> None:
    client = cfg_mod.MCPClientConfig.model_validate(
        {
            "name": "remote",
            "baseUrl": "http://mcp.example",
            "isActive": False,
            "timeout": 3.0,
        },
    )
    assert client.url == "http://mcp.example"
    assert client.enabled is False
    assert client.http_timeout == 3.0
    assert client.transport == "streamable_http"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTP", "streamable_http"),
        ("streamable-http", "streamable_http"),
        ("streamablehttp", "streamable_http"),
        (" SSE ", "sse"),
        ("stdio", "stdio"),
    ],
)
def test_mcp_transport_aliases_fold_to_canonical_values(
    raw: str,
    expected: str,
) -> None:
    if expected == "stdio":
        client = cfg_mod.MCPClientConfig.model_validate(
            {"name": "n", "transport": raw, "command": "ls"},
        )
    else:
        client = cfg_mod.MCPClientConfig.model_validate(
            {"name": "n", "transport": raw, "url": "http://x"},
        )
    assert client.transport == expected


def test_mcp_explicit_fields_win_over_the_aliases() -> None:
    client = cfg_mod.MCPClientConfig.model_validate(
        {
            "name": "n",
            "command": "ls",
            "url": "http://canonical",
            "baseUrl": "http://alias",
            "enabled": True,
            "isActive": False,
            "transport": "stdio",
            "type": "sse",
        },
    )
    assert client.url == "http://canonical"
    assert client.enabled is True
    assert client.transport == "stdio"


def test_mcp_url_only_payload_defaults_to_streamable_http() -> None:
    client = cfg_mod.MCPClientConfig.model_validate(
        {"name": "n", "baseUrl": "http://mcp.example"},
    )
    assert client.transport == "streamable_http"


def test_mcp_command_payload_does_not_infer_a_transport() -> None:
    client = cfg_mod.MCPClientConfig.model_validate(
        {"name": "n", "command": "ls"},
    )
    assert client.transport == "stdio"


def test_mcp_normalizer_passes_non_mapping_input_through() -> None:
    payload = "not-a-mapping"
    assert cfg_mod.MCPClientConfig._normalize_legacy_fields(payload) == payload


def test_stdio_mcp_requires_a_command() -> None:
    with pytest.raises(ConfigurationException) as exc:
        cfg_mod.MCPClientConfig.model_validate(
            {"name": "n", "transport": "stdio"},
        )
    # the key the console surfaces to the user, not just the prose
    assert exc.value.config_key == "mcp.command"
    assert "non-empty command" in exc.value.message


@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
def test_http_mcp_requires_a_url(transport: str) -> None:
    with pytest.raises(ConfigurationException) as exc:
        cfg_mod.MCPClientConfig.model_validate(
            {"name": "n", "transport": transport},
        )
    assert exc.value.config_key == "mcp.url"
    assert transport in exc.value.message


# ---------------------------------------------------------------------------
# SecurityConfig._validate_trusted_proxies
# ---------------------------------------------------------------------------


def test_trusted_proxies_are_normalized_to_network_text() -> None:
    cfg = cfg_mod.SecurityConfig(
        trusted_proxies=["  127.0.0.1  ", "172.17.0.0/16"],
    )
    assert cfg.trusted_proxies == ["127.0.0.1/32", "172.17.0.0/16"]


@pytest.mark.parametrize(
    "entry",
    ["0.0.0.0/0", "::/0", "0.0.0.0", "::", "  0.0.0.0/0  "],
)
def test_trusted_proxies_reject_the_world_open_entries(entry: str) -> None:
    with pytest.raises(ValidationError, match="trusted_proxies"):
        cfg_mod.SecurityConfig(trusted_proxies=[entry])


def test_trusted_proxies_reject_a_non_address() -> None:
    with pytest.raises(ValidationError):
        cfg_mod.SecurityConfig(trusted_proxies=["not-an-ip"])


def test_trusted_proxies_default_never_trusts_a_proxy_header() -> None:
    assert cfg_mod.SecurityConfig().trusted_proxies == []


# ---------------------------------------------------------------------------
# BrowserConfig deprecated knobs and range validation
# ---------------------------------------------------------------------------


def test_deprecated_extension_backend_becomes_a_user_identity() -> None:
    browser = cfg_mod.BrowserConfig.model_validate({"backend": "extension"})
    assert browser.backend == "auto"
    assert browser.identity == "user"


def test_deprecated_extension_backend_keeps_an_explicit_identity() -> None:
    browser = cfg_mod.BrowserConfig.model_validate(
        {"backend": "extension", "identity": "guest"},
    )
    assert browser.backend == "auto"
    assert browser.identity == "guest"


@pytest.mark.parametrize(
    ("context", "expected"),
    [("profile", "avatar"), ("incognito", "guest")],
)
def test_deprecated_context_maps_onto_identity(context: str, expected: str):
    browser = cfg_mod.BrowserConfig.model_validate({"context": context})
    assert browser.identity == expected


def test_deprecated_context_does_not_override_an_explicit_identity() -> None:
    browser = cfg_mod.BrowserConfig.model_validate(
        {"context": "profile", "identity": "user"},
    )
    assert browser.identity == "user"


@pytest.mark.parametrize("engine", ["webkit", "firefox"])
def test_unsupported_engines_fall_back_to_auto(engine: str) -> None:
    assert cfg_mod.BrowserConfig(engine=engine).engine == "auto"


def test_supported_engine_is_kept() -> None:
    assert cfg_mod.BrowserConfig(engine="chromium").engine == "chromium"


def test_connect_cdp_backend_requires_a_cdp_url() -> None:
    with pytest.raises(ValidationError, match="cdp_url"):
        cfg_mod.BrowserConfig(backend="connect_cdp")
    browser = cfg_mod.BrowserConfig(
        backend="connect_cdp",
        cdp_url="http://127.0.0.1:9222",
    )
    assert browser.cdp_url == "http://127.0.0.1:9222"


@pytest.mark.parametrize("port", [-1, 65536])
def test_cdp_port_must_stay_inside_the_valid_range(port: int) -> None:
    with pytest.raises(ValidationError, match="0-65535"):
        cfg_mod.BrowserConfig(cdp_port=port)


@pytest.mark.parametrize("port", [0, 1, 65535])
def test_cdp_port_accepts_the_range_boundaries(port: int) -> None:
    assert cfg_mod.BrowserConfig(cdp_port=port).cdp_port == port


@pytest.mark.parametrize("viewport", [(0, 5), (5, 0), (-1, -1)])
def test_viewport_dimensions_must_be_positive(viewport: tuple) -> None:
    with pytest.raises(ValidationError, match="positive integers"):
        cfg_mod.BrowserConfig(viewport=viewport)


def test_viewport_may_be_absent_or_positive() -> None:
    assert cfg_mod.BrowserConfig().viewport is None
    assert cfg_mod.BrowserConfig(viewport=(1, 1)).viewport == (1, 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"idle_ttl_seconds": 0},
        {"idle_ttl_seconds": -1},
        {"session_idle_ttl_seconds": 0},
        {"exec_timeout_seconds": -0.5},
    ],
)
def test_browser_timeouts_must_be_positive(kwargs: dict) -> None:
    with pytest.raises(ValidationError, match="positive number of seconds"):
        cfg_mod.BrowserConfig(**kwargs)


# ---------------------------------------------------------------------------
# plugin tool defaults
# ---------------------------------------------------------------------------


def test_add_plugin_tool_default_never_overwrites_an_existing_entry():
    tools = {"a": cfg_mod.BuiltinToolConfig(name="a", description="keep")}
    cfg_mod._add_plugin_tool_default(tools, "a", description="new", icon="X")
    assert tools["a"].description == "keep"


def test_add_plugin_tool_default_inserts_a_disabled_visible_tool() -> None:
    tools: dict = {}
    cfg_mod._add_plugin_tool_default(tools, "b", description="d", icon="I")
    added = tools["b"]
    assert added.enabled is False
    assert added.display_to_user is True
    assert added.async_execution is False
    assert added.description == "d"
    assert added.icon == "I"


class _StubRegistry:
    """Registry double with every manifest shape the merge must cope with."""

    @staticmethod
    def get_all_plugin_manifests() -> dict:
        return {
            "solo": {
                "meta": {
                    "tool_name": "solo_tool",
                    "tool_description": "solo desc",
                    "tool_icon": "S",
                },
            },
            "listed": {
                "meta": {
                    "tools": [
                        {"name": "t1", "description": "d1", "icon": "1"},
                        {"name": "t2"},
                    ],
                },
            },
            "malformed": {"meta": {"tools": "not-a-list"}},
            "shapeless": {"meta": {"tools": [{"icon": "x"}, "a-string"]}},
            "empty": {"meta": {}},
            "no_meta": {},
        }


def test_plugin_manifest_merge_collects_named_tools_only(monkeypatch):
    import qwenpaw.plugins.registry as registry_mod

    monkeypatch.setattr(registry_mod, "PluginRegistry", _StubRegistry)
    tools: dict = {}
    cfg_mod._merge_plugin_manifest_tools(tools)
    assert sorted(tools) == ["solo_tool", "t1", "t2"]
    assert tools["t1"].description == "d1"
    assert tools["t1"].icon == "1"
    # entries without a name and non-dict entries contribute nothing
    assert tools["t2"].description == "Tool from plugin listed"
    assert tools["t2"].icon == "🔧"


def test_plugin_manifest_merge_is_skipped_when_the_registry_fails(monkeypatch):
    import qwenpaw.plugins.registry as registry_mod

    class _Boom:
        def __init__(self) -> None:
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr(registry_mod, "PluginRegistry", _Boom)
    tools: dict = {}
    cfg_mod._merge_plugin_manifest_tools(tools)
    assert tools == {}


def test_tools_config_adopts_a_legacy_browser_use_switch(monkeypatch):
    """``browser_use`` is folded into the unified ``browser`` identity."""
    defaults = _default_tools_with(monkeypatch, browser="🌐")
    cfg = cfg_mod.ToolsConfig.model_validate(
        {
            "builtin_tools": {
                "browser_use": {
                    "name": "browser_use",
                    "enabled": False,
                },
            },
        },
    )
    assert "browser_use" not in cfg.builtin_tools
    assert cfg.builtin_tools["browser"].enabled is False
    assert cfg.builtin_tools["browser"].icon == "🌐"
    assert defaults["browser"].icon == "🌐"


def _default_tools_with(monkeypatch, **icons: str) -> dict:
    """Force ``_default_builtin_tools`` to a known, tiny table."""
    table = {
        name: cfg_mod.BuiltinToolConfig(name=name, icon=icon)
        for name, icon in icons.items()
    }
    monkeypatch.setattr(cfg_mod, "_default_builtin_tools", lambda: table)
    return table


def test_tools_config_backfills_new_defaults_and_null_icons(monkeypatch):
    _default_tools_with(monkeypatch, fresh="🆕", existing="⭐")
    cfg = cfg_mod.ToolsConfig.model_validate(
        {
            "builtin_tools": {
                "existing": {"name": "existing", "icon": None},
                "stale": {"name": "stale", "icon": None},
            },
        },
    )
    assert cfg.builtin_tools["fresh"].icon == "🆕"
    assert cfg.builtin_tools["existing"].icon == "⭐"
    # a stale entry keeps its place but gets a serializable empty icon
    assert cfg.builtin_tools["stale"].icon == ""


def test_tools_config_legacy_browser_use_without_a_default(monkeypatch):
    _default_tools_with(monkeypatch, other="🔧")
    cfg = cfg_mod.ToolsConfig.model_validate(
        {"builtin_tools": {"browser_use": {"name": "browser_use"}}},
    )
    assert "browser" not in cfg.builtin_tools
    assert "browser_use" not in cfg.builtin_tools


# ---------------------------------------------------------------------------
# _read_agent_config_snapshot
# ---------------------------------------------------------------------------


def test_snapshot_read_returns_the_stable_bytes(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    path.write_text('{"id": "a"}', encoding="utf-8")
    payload, fingerprint = cfg_mod._read_agent_config_snapshot(path)
    assert payload == b'{"id": "a"}'
    assert fingerprint.size == len(payload)


def test_snapshot_read_gives_up_when_the_file_keeps_changing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "agent.json"
    path.write_text("{}", encoding="utf-8")
    real = cfg_mod._agent_config_fingerprint
    attempts = {"n": 0}

    def always_changing(target: Path):
        attempts["n"] += 1
        base = real(target)
        return cfg_mod._AgentConfigFingerprint(
            device=base.device,
            inode=base.inode + attempts["n"],
            size=base.size,
            mtime_ns=base.mtime_ns,
        )

    monkeypatch.setattr(cfg_mod, "_agent_config_fingerprint", always_changing)
    with pytest.raises(OSError, match="changed repeatedly"):
        cfg_mod._read_agent_config_snapshot(path, retries=2)
    # two attempts, each fingerprinting before and after the read
    assert attempts["n"] == 4


# ---------------------------------------------------------------------------
# build_fallback_agent_profile_config
# ---------------------------------------------------------------------------


def _config_with_profile(agent_id: str, workspace: str) -> cfg_mod.Config:
    config = cfg_mod.Config()
    config.agents.profiles = {
        agent_id: cfg_mod.AgentProfileRef(
            id=agent_id,
            workspace_dir=workspace,
        ),
    }
    return config


def test_fallback_profile_is_derived_from_the_root_config() -> None:
    config = _config_with_profile("helper", "/tmp/ws-helper")
    profile = cfg_mod.build_fallback_agent_profile_config("helper", config)
    assert profile.id == "helper"
    assert profile.name == "Helper"
    assert profile.description == "helper agent"
    assert profile.workspace_dir == "/tmp/ws-helper"


def test_fallback_profile_rejects_an_unknown_agent_id() -> None:
    config = _config_with_profile("helper", "/tmp/ws-helper")
    with pytest.raises(ValueError, match="not found in config"):
        cfg_mod.build_fallback_agent_profile_config("ghost", config)


# ---------------------------------------------------------------------------
# get_model_max_input_length
# ---------------------------------------------------------------------------


def _profile_with_slot(provider_id: str = "", model: str = ""):
    slot = None
    if provider_id or model:
        slot = cfg_mod.ModelSlotConfig(provider_id=provider_id, model=model)
    return cfg_mod.AgentProfileConfig(id="a", name="n", active_model=slot)


def test_context_length_uses_the_provider_resolution(monkeypatch) -> None:
    class _Provider:
        def get_context_size(self, model: str) -> int:
            assert model == "m"
            return 4242

    class _Manager:
        @staticmethod
        def get_instance():
            class _Inner:
                def get_provider(self, provider_id: str):
                    assert provider_id == "pid"
                    return _Provider()

            return _Inner()

    import qwenpaw.providers as providers_mod

    monkeypatch.setattr(providers_mod, "ProviderManager", _Manager)
    assert (
        cfg_mod.get_model_max_input_length(
            _profile_with_slot("pid", "m"),
        )
        == 4242
    )


def test_context_length_falls_back_when_unresolvable(monkeypatch) -> None:
    """Every failure leg must yield the same documented 128k default."""
    import qwenpaw.providers as providers_mod

    default = 128 * 1024

    class _RaisingManager:
        @staticmethod
        def get_instance():
            raise RuntimeError("no provider manager")

    class _ProviderlessManager:
        @staticmethod
        def get_instance():
            class _Inner:
                def get_provider(self, provider_id: str):
                    return None

            return _Inner()

    class _ExplodingManager:
        @staticmethod
        def get_instance():
            class _Inner:
                def get_provider(self, provider_id: str):
                    raise RuntimeError("provider blew up")

            return _Inner()

    profile = _profile_with_slot("pid", "m")
    for manager in (
        _RaisingManager,
        _ProviderlessManager,
        _ExplodingManager,
    ):
        monkeypatch.setattr(providers_mod, "ProviderManager", manager)
        assert cfg_mod.get_model_max_input_length(profile) == default


def test_context_length_recovers_the_slot_from_the_manager(monkeypatch):
    """A profile without ``active_model`` still resolves via the manager."""
    import qwenpaw.providers as providers_mod

    class _Manager:
        @staticmethod
        def get_instance():
            class _Inner:
                def get_active_model(self):
                    return cfg_mod.ModelSlotConfig(
                        provider_id="pid",
                        model="m",
                    )

                def get_provider(self, provider_id: str):
                    class _Provider:
                        def get_context_size(self, model: str) -> int:
                            return 777

                    return _Provider()

            return _Inner()

    monkeypatch.setattr(providers_mod, "ProviderManager", _Manager)
    assert cfg_mod.get_model_max_input_length(_profile_with_slot()) == 777


# ---------------------------------------------------------------------------
# migrate_legacy_config_to_multi_agent
# ---------------------------------------------------------------------------


def test_migration_is_skipped_when_the_default_agent_exists(
    isolated_working_dir,
) -> None:
    wd, _home, config_path = isolated_working_dir
    config = cfg_mod.Config()
    workspace = wd / "workspaces" / "default"
    workspace.mkdir(parents=True)
    (workspace / "agent.json").write_text('{"id": "default"}', "utf-8")
    config.agents.profiles = {
        "default": cfg_mod.AgentProfileRef(
            id="default",
            workspace_dir=str(workspace),
        ),
    }
    _seed_config(config_path, config)

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is False
    # untouched: the pre-existing agent.json is not rewritten
    assert (workspace / "agent.json").read_text("utf-8") == '{"id": "default"}'


def test_migration_runs_when_the_workspace_file_is_missing(
    isolated_working_dir,
) -> None:
    wd, _home, config_path = isolated_working_dir
    config = cfg_mod.Config()
    workspace = wd / "workspaces" / "default"
    workspace.mkdir(parents=True)
    config.agents.profiles = {
        "default": cfg_mod.AgentProfileRef(
            id="default",
            workspace_dir=str(workspace),
        ),
    }
    _seed_config(config_path, config)

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    assert (workspace / "agent.json").is_file()


def test_legacy_migration_creates_the_default_workspace(
    isolated_working_dir,
) -> None:
    wd, home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    legacy.agents.active_agent = ""
    legacy.user_timezone = "Asia/Shanghai"
    _seed_config(config_path, legacy)

    copaw = home / ".copaw"
    (copaw / "sessions").mkdir(parents=True)
    (copaw / "sessions" / "s.json").write_text("{}", encoding="utf-8")
    (copaw / "memory").mkdir()
    (copaw / "jobs.json").write_text("[]", encoding="utf-8")
    for name in ("AGENTS.md", "SOUL.md", "PROFILE.md"):
        (copaw / name).write_text(f"# {name}", encoding="utf-8")

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True

    workspace = wd / "workspaces" / "default"
    assert (workspace / "agent.json").is_file()
    assert (workspace / "sessions" / "s.json").read_text("utf-8") == "{}"
    assert (workspace / "memory").is_dir()
    assert (workspace / "jobs.json").read_text("utf-8") == "[]"
    for name in ("AGENTS.md", "SOUL.md", "PROFILE.md"):
        assert (workspace / name).read_text("utf-8") == f"# {name}"

    persisted = json.loads((workspace / "agent.json").read_text("utf-8"))
    assert persisted["id"] == "default"
    assert persisted["workspace_dir"] == str(workspace)
    assert persisted["system_prompt_files"] == [
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
    ]

    after = config_utils.load_config(config_path)
    assert after.user_timezone == "Asia/Shanghai"
    assert after.agents.active_agent == "default"
    ref = after.agents.profiles["default"]
    assert isinstance(ref, cfg_mod.AgentProfileRef)
    assert ref.workspace_dir == str(workspace)
    # legacy root sections are preserved for downgrade compatibility
    assert after.agents.system_prompt_files == [
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
    ]


def test_legacy_migration_is_idempotent(isolated_working_dir) -> None:
    wd, _home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    _seed_config(config_path, legacy)

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    first = (wd / "workspaces" / "default" / "agent.json").read_bytes()
    assert cfg_mod.migrate_legacy_config_to_multi_agent() is False
    assert (wd / "workspaces" / "default" / "agent.json").read_bytes() == first


def test_legacy_migration_inherits_the_legacy_agent_sections(
    isolated_working_dir,
) -> None:
    wd, _home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    legacy.agents.system_prompt_files = ["SOUL.md"]
    legacy.agents.language = "en"
    _seed_config(config_path, legacy)

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    persisted = json.loads(
        (wd / "workspaces" / "default" / "agent.json").read_text("utf-8"),
    )
    assert persisted["system_prompt_files"] == ["SOUL.md"]
    assert persisted["running"]["memory_manager_backend"] == "remelight"


def test_legacy_migration_survives_an_unavailable_provider_manager(
    isolated_working_dir,
    monkeypatch,
) -> None:
    """The active-model lookup is best effort and must not abort the move."""
    wd, _home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    _seed_config(config_path, legacy)

    class _RaisingManager:
        @staticmethod
        def get_instance():
            raise RuntimeError("providers unavailable")

    import qwenpaw.providers as providers_mod

    monkeypatch.setattr(providers_mod, "ProviderManager", _RaisingManager)
    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    persisted = json.loads(
        (wd / "workspaces" / "default" / "agent.json").read_text("utf-8"),
    )
    assert "active_model" not in persisted


def test_legacy_migration_records_the_global_active_model(
    isolated_working_dir,
    monkeypatch,
) -> None:
    wd, _home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    _seed_config(config_path, legacy)

    slot = cfg_mod.ModelSlotConfig(provider_id="pid", model="m")

    class _Manager:
        @staticmethod
        def get_instance():
            class _Inner:
                def get_active_model(self):
                    return slot

            return _Inner()

    import qwenpaw.providers as providers_mod

    monkeypatch.setattr(providers_mod, "ProviderManager", _Manager)
    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    persisted = json.loads(
        (wd / "workspaces" / "default" / "agent.json").read_text("utf-8"),
    )
    assert persisted["active_model"] == {"provider_id": "pid", "model": "m"}


def test_legacy_migration_never_overwrites_existing_workspace_files(
    isolated_working_dir,
) -> None:
    wd, home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    _seed_config(config_path, legacy)

    workspace = wd / "workspaces" / "default"
    workspace.mkdir(parents=True)
    (workspace / "jobs.json").write_text('["kept"]', encoding="utf-8")
    (workspace / "AGENTS.md").write_text("# kept", encoding="utf-8")

    copaw = home / ".copaw"
    copaw.mkdir()
    (copaw / "jobs.json").write_text('["legacy"]', encoding="utf-8")
    (copaw / "AGENTS.md").write_text("# legacy", encoding="utf-8")

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    assert (workspace / "jobs.json").read_text("utf-8") == '["kept"]'
    assert (workspace / "AGENTS.md").read_text("utf-8") == "# kept"
    # the legacy tree is copied, never moved
    assert (copaw / "jobs.json").is_file()


def test_legacy_migration_ignores_a_missing_legacy_dir(
    isolated_working_dir,
) -> None:
    wd, home, config_path = isolated_working_dir
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    _seed_config(config_path, legacy)
    assert not (home / ".copaw").exists()

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    workspace = wd / "workspaces" / "default"
    assert (workspace / "agent.json").is_file()
    assert not (workspace / "sessions").exists()
    assert not (workspace / "AGENTS.md").exists()


def test_legacy_migration_reads_the_legacy_dir_from_the_fake_home(
    isolated_working_dir,
) -> None:
    """Guard for the ``~/.copaw`` read: it must follow HOME, not the profile.

    Without this the previous tests could pass while silently reading (or
    writing) the real user home, which is exactly the leak this suite must
    not have. The assertion is on the *content* that landed: only the fake
    home can have produced it.
    """
    wd, home, config_path = isolated_working_dir
    assert LEGACY_DIR.parent != home, "fixture home must not be the real one"
    legacy = cfg_mod.Config()
    legacy.agents.profiles = {}
    _seed_config(config_path, legacy)

    marker = "fake-home-soul-marker-7f3a"
    copaw = home / ".copaw"
    copaw.mkdir()
    (copaw / "SOUL.md").write_text(marker, encoding="utf-8")

    assert cfg_mod.migrate_legacy_config_to_multi_agent() is True
    copied = (wd / "workspaces" / "default" / "SOUL.md").read_text("utf-8")
    assert copied == marker
    # the legacy tree is copied, never moved, and nothing is written outside wd
    assert (copaw / "SOUL.md").read_text("utf-8") == marker
    assert list(home.iterdir()) == [copaw]
