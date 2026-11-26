# -*- coding: utf-8 -*-
"""Unit tests for cli/providers_cmd.py.

The ProviderManager singleton, local-model manager and every interactive
prompt are replaced with fakes, so all commands (interactive and
non-interactive) run fully in-process.
"""
# pylint: disable=protected-access,redefined-outer-name,unnecessary-lambda,unused-argument,unused-import,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

import qwenpaw.cli.providers_cmd as pcmd
from qwenpaw.providers.provider import ModelInfo, ProviderInfo


# ---------------------------------------------------------------------------
# fake provider / manager
# ---------------------------------------------------------------------------


class FakeProvider:
    """Minimal stand-in for Provider (attribute-compatible subset)."""

    chat_model = "OpenAIChatModel"

    def __init__(
        self,
        pid: str,
        *,
        name: str | None = None,
        base_url: str = "http://api",
        api_key: str = "",
        require_api_key: bool = True,
        is_local: bool = False,
        is_custom: bool = False,
        freeze_url: bool = False,
        api_key_prefix: str = "",
        api_key_prefixes: list | None = None,
        models: list | None = None,
        extra_models: list | None = None,
    ):
        self.id = pid
        self.name = name or pid.title()
        self.base_url = base_url
        self.api_key = api_key
        self.require_api_key = require_api_key
        self.is_local = is_local
        self.is_custom = is_custom
        self.freeze_url = freeze_url
        self.api_key_prefix = api_key_prefix
        self.api_key_prefixes = api_key_prefixes or []
        self.models = models or []
        self.extra_models = extra_models or []
        self.added: list[ModelInfo] = []
        self.deleted: list[str] = []

    def all_models(self):
        return [*self.models, *self.extra_models]

    async def add_model(self, model_info):
        if any(m.id == model_info.id for m in self.all_models()):
            return False, "exists"
        self.added.append(model_info)
        self.extra_models.append(model_info)
        return True, ""

    async def delete_model(self, model_id):
        if model_id == "missing":
            return False, "not found"
        self.deleted.append(model_id)
        return True, ""


class FakeManager:
    def __init__(self, providers: list[FakeProvider] | None = None):
        self._providers = {p.id: p for p in (providers or [])}
        self.builtin_providers = {"builtin-one"}
        self.saved: list[str] = []
        self.updated: list[tuple[str, dict]] = []
        self.activated: list[tuple[str, str]] = []
        self.active_model = None

    async def list_provider_info(self):
        return [
            ProviderInfo(
                id=p.id,
                name=p.name,
                base_url=p.base_url,
                api_key_prefix=p.api_key_prefix,
                is_custom=p.is_custom,
            )
            for p in self._providers.values()
        ]

    def get_provider(self, pid):
        return self._providers.get(pid)

    def saved_plugin_provider_infos(self):
        return {}

    def get_active_model(self):
        return self.active_model

    def update_provider(self, pid, config):
        if pid not in self._providers:
            return False
        self.updated.append((pid, dict(config)))
        return True

    async def add_custom_provider(self, info):
        if info.id in self._providers:
            raise ValueError("already exists")
        p = FakeProvider(info.id, name=info.name, is_custom=True)
        self._providers[info.id] = p
        return info

    def remove_custom_provider(self, pid):
        if pid == "ghost":
            return False
        self._providers.pop(pid, None)
        return True

    async def activate_model(self, pid, model):
        if pid == "explode":
            raise ValueError("activation refused")
        self.activated.append((pid, model))

    async def add_model_to_provider(self, provider_id, model):
        if provider_id not in self._providers:
            raise ValueError(f"Provider '{provider_id}' not found.")
        ok, message = await self._providers[provider_id].add_model(model)
        if not ok:
            raise ValueError(message)
        self.saved.append(provider_id)

    async def delete_model_from_provider(self, provider_id, model_id):
        if provider_id not in self._providers:
            raise ValueError(f"Provider '{provider_id}' not found.")
        ok, message = await self._providers[provider_id].delete_model(model_id)
        if not ok:
            raise ValueError(message)
        self.saved.append(provider_id)


@pytest.fixture()
def manager(monkeypatch):
    m = FakeManager()
    monkeypatch.setattr(pcmd, "_manager", lambda: m)
    return m


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


class TestMaskApiKey:
    def test_empty(self):
        assert pcmd._mask_api_key("") == ""

    def test_short_fully_masked(self):
        assert pcmd._mask_api_key("sk-123") == "******"

    def test_long_shows_prefix_suffix(self):
        assert pcmd._mask_api_key("sk-1234567890ab") == "sk-1...ab"


class TestIsConfigured:
    def test_local_always_configured(self):
        p = FakeProvider("p", is_local=True, base_url="")
        assert pcmd._is_configured(p) is True

    def test_managed_provider_uses_granted_models(self):
        info = ProviderInfo(
            id="hub-managed",
            name="Hub",
            require_api_key=False,
        )
        assert not pcmd._is_configured(info)
        info.models.append(ModelInfo(id="granted", name="Granted"))
        assert pcmd._is_configured(info)

    def test_api_without_base_url(self):
        assert pcmd._is_configured(FakeProvider("p", base_url="")) is False

    def test_api_key_required_but_missing(self):
        p = FakeProvider("p", api_key="", require_api_key=True)
        assert pcmd._is_configured(p) is False

    def test_api_key_required_and_present(self):
        p = FakeProvider("p", api_key="sk-1", require_api_key=True)
        assert pcmd._is_configured(p) is True

    def test_api_key_not_required(self):
        p = FakeProvider("p", api_key="", require_api_key=False)
        assert pcmd._is_configured(p) is True


class TestAllProviderObjects:
    def test_collects_existing_and_skips_missing(self, manager):
        manager._providers["a"] = FakeProvider("a")
        # make list_provider_info return an id that get_provider can't find
        infos = [
            ProviderInfo(id="a", name="A"),
            ProviderInfo(id="ghost", name="G"),
        ]

        async def fake_list():
            return infos

        manager.list_provider_info = fake_list
        objs = pcmd._all_provider_objects(manager)
        assert [o.id for o in objs] == ["a"]


class TestGetOllamaHost:
    def test_missing_provider_default(self, manager):
        assert pcmd._get_ollama_host() == "http://127.0.0.1:11434"

    def test_provider_without_url(self, manager):
        manager._providers["ollama"] = FakeProvider("ollama", base_url="")
        assert pcmd._get_ollama_host() == "http://127.0.0.1:11434"

    def test_configured_url(self, manager):
        manager._providers["ollama"] = FakeProvider(
            "ollama",
            base_url="http://remote:11434",
        )
        assert pcmd._get_ollama_host() == "http://remote:11434"


# ---------------------------------------------------------------------------
# interactive selection helpers
# ---------------------------------------------------------------------------


class TestSelectProviderInteractive:
    def test_returns_chosen_id(self, manager, monkeypatch):
        manager._providers["a"] = FakeProvider("a", api_key="k")
        manager._providers["b"] = FakeProvider("b", base_url="")
        monkeypatch.setattr(
            pcmd,
            "prompt_choice",
            lambda q, options, default=None: options[0],
        )
        assert pcmd._select_provider_interactive() == "a"

    def test_default_selection(self, manager, monkeypatch):
        manager._providers["a"] = FakeProvider("a", api_key="k")
        manager._providers["b"] = FakeProvider("b", api_key="k")

        seen = {}

        def fake_prompt(q, options, default=None):
            seen["default"] = default
            return default

        monkeypatch.setattr(pcmd, "prompt_choice", fake_prompt)
        assert pcmd._select_provider_interactive(default_pid="b") == "b"
        assert "B" in seen["default"]


class TestConfigureProviderApiKeyInteractive:
    def test_unknown_provider_exits(self, manager):
        with pytest.raises(SystemExit) as exc:
            pcmd.configure_provider_api_key_interactive("ghost")
        assert exc.value.code == 1

    def test_freeze_url_skips_prompt_and_no_key_needed(
        self,
        manager,
        monkeypatch,
        capsys,
    ):
        p = FakeProvider(
            "fixed",
            base_url="http://fixed",
            freeze_url=True,
            require_api_key=False,
        )
        manager._providers["fixed"] = p
        got = pcmd.configure_provider_api_key_interactive("fixed")
        assert got == "fixed"
        assert "fixed, not editable" in capsys.readouterr().out
        assert manager.updated == []

    def test_empty_base_url_rejected_for_custom(
        self,
        manager,
        monkeypatch,
    ):
        p = FakeProvider("cust", base_url="", is_custom=True)
        manager._providers["cust"] = p
        monkeypatch.setattr(pcmd.click, "prompt", lambda *a, **kw: "  ")
        with pytest.raises(SystemExit) as exc:
            pcmd.configure_provider_api_key_interactive("cust")
        assert exc.value.code == 1

    def test_empty_base_url_keeps_existing_for_builtin(
        self,
        manager,
        monkeypatch,
    ):
        p = FakeProvider("builtin-one", base_url="http://old", api_key="k")
        manager._providers["builtin-one"] = p
        monkeypatch.setattr(pcmd.click, "prompt", lambda *a, **kw: "")
        got = pcmd.configure_provider_api_key_interactive("builtin-one")
        assert got == "builtin-one"
        assert manager.updated == []

    def test_update_failure_exits(self, manager, monkeypatch):
        p = FakeProvider("p1", api_key="old")
        manager._providers["p1"] = p

        def fake_prompt(*a, **kw):
            return "http://u" if "URL" in str(a[0]) else "sk-new"

        monkeypatch.setattr(pcmd.click, "prompt", fake_prompt)

        def fail_update(pid, cfg):
            return False

        monkeypatch.setattr(manager, "update_provider", fail_update)
        with pytest.raises(SystemExit) as exc:
            pcmd.configure_provider_api_key_interactive("p1")
        assert exc.value.code == 1

    def test_success_masks_key_in_summary(
        self,
        manager,
        monkeypatch,
        capsys,
    ):
        p = FakeProvider("p1", api_key="")
        manager._providers["p1"] = p
        answers = iter(["http://new-base", "sk-abcdefghij"])
        monkeypatch.setattr(
            pcmd.click,
            "prompt",
            lambda *a, **kw: next(answers),
        )
        got = pcmd.configure_provider_api_key_interactive("p1")
        assert got == "p1"
        pid, cfg = manager.updated[-1]
        assert pid == "p1"
        assert cfg["api_key"] == "sk-abcdefghij"
        assert cfg["base_url"] == "http://new-base"
        assert "sk-a...ij" in capsys.readouterr().out

    def test_selects_provider_when_none_given(
        self,
        manager,
        monkeypatch,
    ):
        p = FakeProvider(
            "only",
            api_key="k",
            freeze_url=True,
            require_api_key=False,
        )
        manager._providers["only"] = p
        monkeypatch.setattr(
            pcmd,
            "_select_provider_interactive",
            lambda q: "only",
        )
        assert pcmd.configure_provider_api_key_interactive() == "only"


class TestAddModelsInteractive:
    def test_unknown_provider_exits(self, manager):
        with pytest.raises(SystemExit):
            pcmd._add_models_interactive("ghost", None)

    def test_ollama_returns_immediately(self, manager):
        manager._providers["ollama"] = FakeProvider("ollama")
        pcmd._add_models_interactive("ollama", None)  # no prompts -> returns

    def test_add_flow_then_stop(self, manager, monkeypatch, capsys):
        p = FakeProvider("p1")
        manager._providers["p1"] = p
        confirms = iter([True, False])
        prompts = iter(["m-1", "Model One"])
        monkeypatch.setattr(
            pcmd.click,
            "confirm",
            lambda *a, **kw: next(confirms),
        )
        monkeypatch.setattr(
            pcmd.click,
            "prompt",
            lambda *a, **kw: next(prompts),
        )
        pcmd._add_models_interactive("p1", None)
        assert [m.id for m in p.added] == ["m-1"]
        assert "m-1" in capsys.readouterr().out
        assert manager.saved == ["p1"]

    def test_empty_model_id_reprompts(self, manager, monkeypatch):
        p = FakeProvider("p1")
        manager._providers["p1"] = p
        confirms = iter([True, True, False])
        prompts = iter(["", "m-2", "Two"])
        monkeypatch.setattr(
            pcmd.click,
            "confirm",
            lambda *a, **kw: next(confirms),
        )
        monkeypatch.setattr(
            pcmd.click,
            "prompt",
            lambda *a, **kw: next(prompts),
        )
        pcmd._add_models_interactive("p1", None)
        assert [m.id for m in p.added] == ["m-2"]

    def test_duplicate_model_reports_error(self, manager, monkeypatch):
        p = FakeProvider("p1", models=[ModelInfo(id="m-1", name="M1")])
        manager._providers["p1"] = p
        confirms = iter([True, False])
        prompts = iter(["m-1", "dup"])
        monkeypatch.setattr(
            pcmd.click,
            "confirm",
            lambda *a, **kw: next(confirms),
        )
        monkeypatch.setattr(
            pcmd.click,
            "prompt",
            lambda *a, **kw: next(prompts),
        )
        pcmd._add_models_interactive("p1", None)
        assert p.added == []

    def test_add_model_exception_handled(self, manager, monkeypatch):
        p = FakeProvider("p1")
        manager._providers["p1"] = p

        async def boom(mi):
            raise ValueError("nope")

        p.add_model = boom
        confirms = iter([True, False])
        prompts = iter(["m-1", "M"])
        monkeypatch.setattr(
            pcmd.click,
            "confirm",
            lambda *a, **kw: next(confirms),
        )
        monkeypatch.setattr(
            pcmd.click,
            "prompt",
            lambda *a, **kw: next(prompts),
        )
        pcmd._add_models_interactive("p1", None)  # must not raise


class TestPickHelpers:
    def test_pick_model_from_list_default(self, monkeypatch):
        models = [ModelInfo(id="a", name="A"), ModelInfo(id="b", name="B")]
        monkeypatch.setattr(
            pcmd,
            "prompt_choice",
            lambda q, options, default=None: default,
        )
        assert pcmd._pick_model_from_list(models, "q", "b") == "b"

    def test_pick_model_from_list_no_default(self, monkeypatch):
        models = [ModelInfo(id="a", name="A")]
        monkeypatch.setattr(
            pcmd,
            "prompt_choice",
            lambda q, options, default=None: options[0],
        )
        assert pcmd._pick_model_from_list(models, "q") == "a"

    def test_pick_model_free_text_empty_exits(self, monkeypatch):
        monkeypatch.setattr(pcmd.click, "prompt", lambda *a, **kw: "  ")
        with pytest.raises(SystemExit):
            pcmd._pick_model_free_text("q")

    def test_pick_model_free_text_returns_value(self, monkeypatch):
        monkeypatch.setattr(pcmd.click, "prompt", lambda *a, **kw: " m1 ")
        assert pcmd._pick_model_free_text("q", "old") == "m1"


class TestFilterEligible:
    def test_filters_unconfigured(self):
        ok = FakeProvider("ok", api_key="k")
        bad = FakeProvider("bad", base_url="")
        assert pcmd._filter_eligible([ok, bad]) == [ok]


class TestSelectLlmModel:
    def test_use_defaults_prefers_current(self):
        p = FakeProvider("p", models=[ModelInfo(id="m1", name="M1")])
        slot = SimpleNamespace(provider_id="p", model="m1")
        assert pcmd._select_llm_model(p, "p", slot, use_defaults=True) == "m1"

    def test_use_defaults_first_model_when_no_current(self):
        p = FakeProvider("p", models=[ModelInfo(id="m1", name="M1")])
        assert pcmd._select_llm_model(p, "p", None, use_defaults=True) == "m1"

    def test_use_defaults_empty_when_no_models(self):
        p = FakeProvider("p")
        assert pcmd._select_llm_model(p, "p", None, use_defaults=True) == ""

    def test_interactive_picks_from_list(self, monkeypatch):
        p = FakeProvider("p", models=[ModelInfo(id="m1", name="M1")])
        monkeypatch.setattr(
            pcmd,
            "_pick_model_from_list",
            lambda models, text, current_model="": "m1",
        )
        assert pcmd._select_llm_model(p, "p", None, use_defaults=False) == "m1"

    def test_interactive_free_text_when_no_models(self, monkeypatch):
        p = FakeProvider("p")
        monkeypatch.setattr(
            pcmd,
            "_pick_model_free_text",
            lambda text, current_model="": "typed",
        )
        assert (
            pcmd._select_llm_model(p, "p", None, use_defaults=False) == "typed"
        )


# ---------------------------------------------------------------------------
# configure_llm_slot_interactive
# ---------------------------------------------------------------------------


class TestConfigureLlmSlotInteractive:
    def test_no_eligible_with_defaults_notes(self, manager, capsys):
        pcmd.configure_llm_slot_interactive(use_defaults=True)
        assert "No LLM provider configured" in capsys.readouterr().out

    def test_no_eligible_interactive_configures_one(
        self,
        manager,
        monkeypatch,
        capsys,
    ):
        p = FakeProvider(
            "p1",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["p1"] = p
        # first pass: configured() True so it is eligible right away
        monkeypatch.setattr(
            pcmd,
            "prompt_choice",
            lambda q, options, default=None: options[0],
        )
        pcmd.configure_llm_slot_interactive()
        assert manager.activated == [("p1", "m")]

    def test_eligible_empty_after_retry_exits(
        self,
        manager,
        monkeypatch,
    ):
        monkeypatch.setattr(
            pcmd,
            "_configure_provider_api_key",
            lambda provider_id, api: "p1",
        )
        monkeypatch.setattr(
            pcmd,
            "_add_models_interactive",
            lambda pid, api: None,
        )
        manager._providers.clear()  # nothing becomes eligible
        with pytest.raises(SystemExit) as exc:
            pcmd.configure_llm_slot_interactive()
        assert exc.value.code == 1

    def test_use_defaults_keeps_current_slot(self, manager, capsys):
        p = FakeProvider(
            "p1",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["p1"] = p
        manager.active_model = SimpleNamespace(provider_id="p1", model="old")
        pcmd.configure_llm_slot_interactive(use_defaults=True)
        assert manager.activated == [("p1", "old")]

    def test_use_defaults_first_eligible_when_slot_stale(
        self,
        manager,
        capsys,
    ):
        p = FakeProvider(
            "p1",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["p1"] = p
        manager.active_model = SimpleNamespace(provider_id="gone", model="x")
        pcmd.configure_llm_slot_interactive(use_defaults=True)
        assert manager.activated == [("p1", "m")]

    def test_use_defaults_no_default_model_notes(
        self,
        manager,
        capsys,
    ):
        p = FakeProvider("p1", api_key="k")
        manager._providers["p1"] = p
        pcmd.configure_llm_slot_interactive(use_defaults=True)
        assert "No default model" in capsys.readouterr().out
        assert manager.activated == []

    def test_activation_error_exits_interactive(self, manager, monkeypatch):
        p = FakeProvider(
            "explode",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["explode"] = p
        monkeypatch.setattr(
            pcmd,
            "prompt_choice",
            lambda q, options, default=None: options[0],
        )
        with pytest.raises(SystemExit) as exc:
            pcmd.configure_llm_slot_interactive()
        assert exc.value.code == 1

    def test_activation_error_soft_with_defaults(
        self,
        manager,
        monkeypatch,
        capsys,
    ):
        p = FakeProvider(
            "explode",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["explode"] = p
        pcmd.configure_llm_slot_interactive(use_defaults=True)
        assert "Skip default activation" in capsys.readouterr().out

    def test_provider_vanishes_exits(self, manager, monkeypatch):
        p = FakeProvider(
            "p1",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["p1"] = p

        def choose(q, options, default=None):
            manager._providers.pop("p1")
            return options[0]

        monkeypatch.setattr(pcmd, "prompt_choice", choose)
        with pytest.raises(SystemExit):
            pcmd.configure_llm_slot_interactive()


class TestConfigureProvidersInteractive:
    def test_use_defaults_delegates(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            pcmd,
            "_configure_llm_slot",
            lambda use_defaults, api: seen.append(use_defaults),
        )
        pcmd.configure_providers_interactive(use_defaults=True)
        assert seen == [True]

    def test_local_provider_goes_straight_to_activation(
        self,
        manager,
        monkeypatch,
    ):
        p = FakeProvider("qwenpaw-local", is_local=True, require_api_key=False)
        manager._providers["qwenpaw-local"] = p
        activated = []
        monkeypatch.setattr(
            pcmd,
            "_configure_provider_api_key",
            lambda provider_id, api: "qwenpaw-local",
        )
        monkeypatch.setattr(
            pcmd,
            "_configure_llm_slot",
            lambda use_defaults, api: activated.append(True),
        )
        pcmd.configure_providers_interactive()
        assert activated == [True]

    def test_unknown_provider_after_config_exits(self, manager, monkeypatch):
        monkeypatch.setattr(
            pcmd,
            "_configure_provider_api_key",
            lambda provider_id, api: "ghost",
        )
        with pytest.raises(SystemExit):
            pcmd.configure_providers_interactive()

    def test_loop_then_activate(self, manager, monkeypatch):
        p = FakeProvider(
            "p1",
            api_key="k",
            models=[ModelInfo(id="m", name="M")],
        )
        manager._providers["p1"] = p
        monkeypatch.setattr(
            pcmd,
            "_configure_provider_api_key",
            lambda provider_id, api: "p1",
        )
        added = []
        monkeypatch.setattr(
            pcmd,
            "_prompt_add_models",
            lambda pid, provider, api: added.append(pid),
        )
        monkeypatch.setattr(pcmd.click, "confirm", lambda *a, **kw: False)
        activated = []
        monkeypatch.setattr(
            pcmd,
            "_configure_llm_slot",
            lambda use_defaults, api: activated.append(True),
        )
        pcmd.configure_providers_interactive()
        assert added == ["p1"]
        assert activated == [True]


# ---------------------------------------------------------------------------
# CLI commands (models group)
# ---------------------------------------------------------------------------


class TestListCmd:
    def test_lists_providers_models_and_slot(self, manager):
        api = FakeProvider(
            "p-api",
            name="API One",
            api_key="sk-1234567890",
            models=[ModelInfo(id="m1", name="Model One")],
            extra_models=[ModelInfo(id="m2", name="Model Two")],
            api_key_prefixes=["sk-", "pk-"],
        )
        local = FakeProvider(
            "p-local",
            name="Local",
            is_local=True,
            models=[ModelInfo(id="lm", name="Local Model")],
            extra_models=[ModelInfo(id="manual", name="Added Local Model")],
        )
        empty_local = FakeProvider(
            "p-local2",
            name="Empty Local",
            is_local=True,
        )
        bare = FakeProvider(
            "p-bare",
            name="Bare",
            base_url="",
            api_key_prefix="",
        )
        manager._providers.update(
            {
                "p-api": api,
                "p-local": local,
                "p-local2": empty_local,
                "p-bare": bare,
            },
        )
        manager.active_model = SimpleNamespace(
            provider_id="p-api",
            model="m1",
        )
        res = CliRunner().invoke(pcmd.models_group, ["list"])
        assert res.exit_code == 0
        assert "API One (p-api)" in res.output
        assert "[custom]" not in res.output
        assert "sk-1...90" in res.output
        assert "sk-, pk-" in res.output
        assert "Model Two (m2) [user-added]" in res.output
        assert "Local (p-local) [local]" in res.output
        assert "Local Model" in res.output
        assert "Added Local Model" in res.output
        assert "No models configured." in res.output
        assert "qwenpaw models --help" in res.output
        assert "qwenpaw models download" not in res.output
        assert "(not set)" in res.output
        assert "p-api / m1" in res.output

    def test_custom_tag_and_unset_slot(self, manager):
        manager._providers["c"] = FakeProvider("c", is_custom=True)
        res = CliRunner().invoke(pcmd.models_group, ["list"])
        assert res.exit_code == 0
        assert "[custom]" in res.output
        assert "(not configured)" in res.output


class TestAddProviderCmd:
    def test_success(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            [
                "add-provider",
                "myprov",
                "-n",
                "My Provider",
                "-u",
                "http://x",
                "--api-key-prefix",
                "mk-",
            ],
        )
        assert res.exit_code == 0
        assert "created" in res.output
        assert "base_url: http://x" in res.output

    def test_returned_id_differs_shows_requested(
        self,
        manager,
    ):
        async def renamed(info):
            return ProviderInfo(
                id="sanitized-id",
                name=info.name,
                is_custom=True,
            )

        manager.add_custom_provider = renamed
        res = CliRunner().invoke(
            pcmd.models_group,
            ["add-provider", "my prov!", "-n", "Renamed"],
        )
        assert res.exit_code == 0
        assert "requested id: my prov!" in res.output

    def test_duplicate_fails(self, manager):
        manager._providers["dup"] = FakeProvider("dup")
        res = CliRunner().invoke(
            pcmd.models_group,
            ["add-provider", "dup", "-n", "Dup"],
        )
        assert res.exit_code == 1
        assert "Error" in res.output


class TestRealManagerAccessor:
    def test_manager_returns_provider_manager_singleton(self):
        # exercises the unpatched module-level accessor
        from qwenpaw.providers.provider_manager import ProviderManager

        assert pcmd._manager() is ProviderManager.get_instance()


class TestRemoveProviderCmd:
    def test_builtin_rejected(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-provider", "builtin-one"],
        )
        assert res.exit_code == 1
        assert "built-in" in res.output

    def test_declined_confirmation(self, manager):
        manager._providers["c"] = FakeProvider("c", is_custom=True)
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-provider", "c"],
            input="n\n",
        )
        assert res.exit_code == 0
        assert "c" in manager._providers

    def test_removed_with_yes(self, manager):
        manager._providers["c"] = FakeProvider("c", is_custom=True)
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-provider", "c", "-y"],
        )
        assert res.exit_code == 0
        assert "deleted" in res.output
        assert "c" not in manager._providers

    def test_missing_provider_error(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-provider", "ghost", "-y"],
        )
        assert res.exit_code == 1
        assert "not found" in res.output


class TestAddModelCmd:
    def test_ollama_rejected(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["add-model", "ollama", "-m", "x", "-n", "X"],
        )
        assert res.exit_code == 1
        assert "Ollama models cannot be added manually" in res.output

    def test_unknown_provider(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["add-model", "ghost", "-m", "x", "-n", "X"],
        )
        assert res.exit_code == 1
        assert "not found" in res.output

    def test_success_saves_provider(self, manager):
        manager._providers["p1"] = FakeProvider("p1")
        res = CliRunner().invoke(
            pcmd.models_group,
            ["add-model", "p1", "-m", "m9", "-n", "Model Nine"],
        )
        assert res.exit_code == 0
        assert "added to 'p1'" in res.output
        assert manager.saved == ["p1"]

    def test_add_model_raises_value_error(self, manager):
        p = FakeProvider("p1", models=[ModelInfo(id="m1", name="M1")])
        manager._providers["p1"] = p

        async def boom(mi):
            raise ValueError("rejected by provider")

        p.add_model = boom
        res = CliRunner().invoke(
            pcmd.models_group,
            ["add-model", "p1", "-m", "m1", "-n", "dup"],
        )
        assert res.exit_code == 1
        assert "rejected by provider" in res.output


class TestRemoveModelCmd:
    def test_ollama_rejected(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-model", "ollama", "-m", "x"],
        )
        assert res.exit_code == 1
        assert "cannot be removed via this command" in res.output

    def test_unknown_provider(self, manager):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-model", "ghost", "-m", "x"],
        )
        assert res.exit_code == 1

    def test_success(self, manager):
        p = FakeProvider("p1")
        manager._providers["p1"] = p
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-model", "p1", "-m", "m1"],
        )
        assert res.exit_code == 0
        assert "removed from 'p1'" in res.output
        assert manager.saved == ["p1"]

    def test_delete_failure_message(self, manager):
        p = FakeProvider("p1")
        manager._providers["p1"] = p
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-model", "p1", "-m", "missing"],
        )
        assert res.exit_code == 1
        assert "not found" in res.output


# ---------------------------------------------------------------------------
# local model commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["download", "local", "remove-local"])
def test_local_commands_are_owned_by_plugins(command):
    result = CliRunner().invoke(pcmd.models_group, [command])
    assert result.exit_code == 2
    assert "No such command" in result.output


class TestSimpleDelegatingCmds:
    def test_config_delegates(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            pcmd,
            "configure_providers_interactive",
            lambda: called.append(True),
        )
        res = CliRunner().invoke(pcmd.models_group, ["config"])
        assert res.exit_code == 0
        assert called == [True]

    def test_config_key_delegates(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            pcmd,
            "configure_provider_api_key_interactive",
            lambda provider_id=None: seen.append(provider_id) or "x",
        )
        res = CliRunner().invoke(
            pcmd.models_group,
            ["config-key", "prov1"],
        )
        assert res.exit_code == 0
        assert seen == ["prov1"]

    def test_set_llm_delegates(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            pcmd,
            "configure_llm_slot_interactive",
            lambda use_defaults=False: called.append(True),
        )
        res = CliRunner().invoke(pcmd.models_group, ["set-llm"])
        assert res.exit_code == 0
        assert called == [True]


@pytest.mark.parametrize(
    "require_api_key,answers,expected",
    [
        (
            True,
            "http://new-base\nprobe-key\n",
            {"base_url": "http://new-base", "api_key": "probe-key"},
        ),
        (True, "\n******\n", {}),
        (False, "http://new-base\n", {"base_url": "http://new-base"}),
    ],
)
def test_config_key_reads_and_writes_the_explicit_target(
    monkeypatch,
    require_api_key,
    answers,
    expected,
):
    import httpx

    from qwenpaw.cli.main import cli
    from qwenpaw.cli import http

    calls = []
    monkeypatch.setattr(
        pcmd,
        "_manager",
        lambda: pytest.fail("read local settings"),
    )

    def respond(request):
        import json

        assert (
            str(request.url) == "http://remote:8123/api/models/example/config"
        )
        calls.append(
            (
                request.method,
                json.loads(request.content) if request.content else None,
            ),
        )
        return httpx.Response(
            200,
            json={
                "id": "example",
                "name": "Example",
                "base_url": "http://remote-base",
                "api_key": "******",
                "require_api_key": require_api_key,
            },
        )

    monkeypatch.setattr(
        http,
        "client",
        lambda url: httpx.Client(
            base_url=url + "/api/",
            transport=httpx.MockTransport(respond),
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            "--host",
            "remote",
            "--port",
            "8123",
            "models",
            "config-key",
            "EXAMPLE",
        ],
        input=answers,
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert "http://remote-base" in result.output
    assert calls == [("GET", None)] + (
        [("PUT", {**expected, "auto_discover": False})] if expected else []
    )


@pytest.mark.parametrize(
    "options,allow_local",
    [
        (["--host", "127.0.0.1", "--port", "8123"], True),
        (["--host", "127.0.0.1", "--port", "9123"], False),
    ],
)
def test_models_cli_preserves_local_access_under_web_auth(
    monkeypatch,
    manager,
    options,
    allow_local,
):
    import httpx
    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli

    manager._providers["example"] = FakeProvider(
        "example",
        require_api_key=False,
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(401)

    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)
    monkeypatch.setattr(
        http,
        "local_runtime_url",
        lambda: "http://127.0.0.1:8123",
    )
    monkeypatch.setattr(
        http,
        "client",
        lambda url: httpx.Client(
            base_url=url + "/api/",
            transport=httpx.MockTransport(respond),
        ),
    )
    result = CliRunner().invoke(
        cli,
        [*options, "models", "config-key", "example"],
        input="http://changed\n",
    )
    assert result.exit_code == (0 if allow_local else 1), result.output
    if allow_local:
        assert all(request.method == "GET" for request in requests)
        assert manager.updated == [("example", {"base_url": "http://changed"})]
    else:
        assert all(request.url.port == 9123 for request in requests)
        assert not manager.updated and not manager.saved


@pytest.mark.parametrize("shared", [False, True])
def test_config_wizard_uses_selected_app_through_activation(
    monkeypatch,
    manager,
    shared,
):
    import json
    import httpx
    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli

    pid = "example"
    if shared:
        manager._providers[pid] = FakeProvider(
            pid,
            require_api_key=False,
            models=[ModelInfo(id="local", name="Local")],
        )
    provider = {
        "id": pid,
        "name": "Example",
        "base_url": "http://old",
        "require_api_key": False,
        "models": [],
    }
    writes = []
    running = "http://selected"

    def respond(request):
        nonlocal running
        assert request.url.host == "selected"
        path = request.url.path
        if request.method == "GET":
            if path == "/api/models":
                return httpx.Response(200, json=[provider])
            if path == "/api/models/active":
                assert request.url.params["scope"] == "global"
                return httpx.Response(200, json={"active_llm": None})
            assert path == "/api/models/example/config"
            return httpx.Response(200, json=provider)
        payload = json.loads(request.content) if request.content else None
        writes.append((request.method, path, payload))
        if path == "/api/models/example/config":
            running = "http://another-app"
        if path == "/api/models/example/models":
            provider["models"].append(payload)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        http,
        "client",
        lambda url: httpx.Client(
            base_url=url + "/api/",
            transport=httpx.MockTransport(respond),
        ),
    )
    monkeypatch.setattr(
        pcmd,
        "prompt_choice",
        lambda prompt_text, options, default: options[0],
    )
    monkeypatch.setattr(http, "local_runtime_url", lambda: running)
    target = [] if shared else ["--host", "selected"]
    result = CliRunner().invoke(
        cli,
        [*target, "models", "config"],
        input="http://new\ny\nremote-model\nRemote model\nn\nn\n",
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert writes == [
        (
            "PUT",
            "/api/models/example/config",
            {"base_url": "http://new", "auto_discover": False},
        ),
        (
            "POST",
            "/api/models/example/models",
            {"id": "remote-model", "name": "Remote model"},
        ),
        (
            "PUT",
            "/api/models/active",
            {"provider_id": pid, "model": "remote-model", "scope": "global"},
        ),
    ]
    assert not manager.activated and not manager.saved


def test_custom_provider_lifecycle_uses_the_selected_app(monkeypatch):
    import json
    import httpx
    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli

    requests = []
    monkeypatch.setattr(
        pcmd,
        "_manager",
        lambda: pytest.fail("selected App owns the provider"),
    )

    def respond(request):
        assert request.url.host == "selected"
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/models/custom-providers":
            body = json.loads(request.content)
            assert body["default_base_url"] == "http://provider"
            assert body["auto_discover"] is False
            return httpx.Response(201, json=body)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        http,
        "client",
        lambda url: httpx.Client(
            base_url=url + "/api/",
            transport=httpx.MockTransport(respond),
        ),
    )
    for args in (
        ["add-provider", "example", "-n", "Example", "-u", "http://provider"],
        ["add-model", "example", "-m", "m", "-n", "Model"],
        ["remove-model", "example", "-m", "m"],
        ["remove-provider", "example", "--yes"],
    ):
        result = CliRunner().invoke(
            cli,
            ["--host", "selected", "models", *args],
        )
        assert result.exit_code == 0, result.output
    assert requests == [
        ("POST", "/api/models/custom-providers"),
        ("POST", "/api/models/example/models"),
        ("DELETE", "/api/models/example/models/m"),
        ("DELETE", "/api/models/custom-providers/example"),
    ]


def test_config_key_with_an_app_that_only_lists_providers(monkeypatch):
    import httpx

    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli

    provider = {
        "id": "remote-only",
        "name": "Remote",
        "base_url": "http://remote-base",
    }

    def respond(request):
        assert request.method == "GET"
        if request.url.path.endswith("/config"):
            return httpx.Response(405)
        assert request.url.path == "/api/models"
        return httpx.Response(200, json=[provider])

    monkeypatch.setattr(
        pcmd,
        "_manager",
        lambda: pytest.fail("read local settings"),
    )
    monkeypatch.setattr(
        http,
        "client",
        lambda url: httpx.Client(
            base_url=url + "/api/",
            transport=httpx.MockTransport(respond),
        ),
    )
    result = CliRunner().invoke(
        cli,
        ["--host", "remote", "models", "config-key", "remote-only"],
        input="\n\n",
    )
    assert result.exit_code == 0, result.exception
    assert "configuration unchanged" in result.output


@pytest.mark.parametrize("require_api_key", [False, True])
@pytest.mark.parametrize("online", [False, True])
def test_unavailable_plugin_provider_connection_change_invalidates_snapshot(
    tmp_path,
    monkeypatch,
    require_api_key,
    online,
):
    import json

    from qwenpaw.config import utils
    from qwenpaw.providers import provider_manager as managers
    from qwenpaw.providers import provider_manager_persistence as persistence

    monkeypatch.setattr(utils, "is_qwenpaw_running", lambda: False)
    # Exercise persistence without reading the user's encryption key store.
    monkeypatch.setattr(
        persistence,
        "decrypt_dict_fields",
        lambda data, fields: dict(data),
    )

    def encrypt(data, fields):
        return {
            key: (
                "probe-encrypted:" + value
                if key in fields and isinstance(value, str)
                else value
            )
            for key, value in data.items()
        }

    monkeypatch.setattr(persistence, "encrypt_dict_fields", encrypt)
    monkeypatch.setattr(managers, "SECRET_DIR", tmp_path / "secrets")
    manager = managers.ProviderManager()
    path = manager.plugin_path / "example.json"
    snapshot = ProviderInfo(
        id="example",
        name="Example",
        base_url="https://old.invalid",
        api_key="old-key",
        require_api_key=require_api_key,
        models_last_synced_at="2026-01-01T00:00:00Z",
        models_last_sync_error="old error",
        models_syncing=True,
        models=[
            {
                "id": "curated",
                "name": "Curated",
                "availability_status": "available",
                "billing": "free",
                "is_free": True,
            },
        ],
        discovered_models=[{"id": "old-only", "name": "Old only"}],
    )
    raw = {
        **snapshot.model_dump(mode="json"),
        "preserved_plugin_field": {"value": 17},
    }
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(pcmd, "_manager", lambda: manager)
    if online:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from qwenpaw.app.routers.providers import router
        from qwenpaw.cli import http

        app = FastAPI()
        app.state.provider_manager = manager
        app.include_router(router)

        class Client(TestClient):
            def get(self, url, **kwargs):
                response = super().get(url, **kwargs)
                data = response.json()
                assert response.status_code == 200
                assert data["api_key"] == "******"
                assert data["base_url"] == "https://old.invalid"
                assert "custom_headers" not in data
                return response

            def put(self, url, **kwargs):
                response = super().put(url, **kwargs)
                assert response.status_code == 200
                assert response.json()["api_key"] == "******"
                return response

        monkeypatch.setattr(http, "local_runtime_url", lambda: "http://app")
        monkeypatch.setattr(
            http,
            "client",
            lambda url: Client(app, base_url=url),
        )
    result = CliRunner().invoke(
        pcmd.models_group,
        ["config-key", "EXAMPLE"],
        input="https://new.invalid\nnew-key\n",
    )
    assert result.exit_code == 0, (result.output, result.exception)
    actual = json.loads(path.read_text())
    assert actual["base_url"] == "https://new.invalid"
    assert actual["api_key"] == (
        "probe-encrypted:new-key" if require_api_key else "old-key"
    )
    assert actual["discovered_models"] == []
    assert actual["models_last_synced_at"] is None
    assert actual["models_last_sync_error"] is None
    assert actual["models_syncing"] is False
    assert actual["models"][0]["availability_status"] == "unverified"
    assert actual["models"][0]["billing"] == "unknown"
    assert actual["preserved_plugin_field"] == {"value": 17}


@pytest.mark.parametrize("action", ["add", "remove"])
def test_plugin_model_command_persists_owned_snapshot(
    tmp_path,
    monkeypatch,
    action,
):
    import json
    from qwenpaw.config import utils
    from qwenpaw.providers import provider_manager as managers
    from qwenpaw.providers.openai_provider import OpenAIProvider

    monkeypatch.setattr(managers, "SECRET_DIR", tmp_path)
    monkeypatch.setattr(utils, "is_qwenpaw_running", lambda: False)
    manager = managers.ProviderManager()
    asyncio.run(
        manager.register_plugin_provider_async(
            "example",
            OpenAIProvider,
            "Example",
            "https://example.invalid/v1",
            metadata={"chat_model": "OpenAIChatModel"},
        ),
    )
    monkeypatch.setattr(pcmd, "_manager", lambda: manager)
    runner = CliRunner()
    added = runner.invoke(
        pcmd.models_group,
        [
            "add-model",
            "example",
            "-m",
            "demo",
            "-n",
            "Demo",
        ],
    )
    assert added.exit_code == 0, added.output
    if action == "remove":
        result = runner.invoke(
            pcmd.models_group,
            [
                "remove-model",
                "example",
                "-m",
                "demo",
            ],
        )
        assert result.exit_code == 0, result.output
    else:
        duplicate = runner.invoke(
            pcmd.models_group,
            [
                "add-model",
                "example",
                "-m",
                "demo",
                "-n",
                "Demo",
            ],
        )
        assert duplicate.exit_code == 1
        assert "added to" not in duplicate.output
    data = json.loads((manager.plugin_path / "example.json").read_text())
    assert [model["id"] for model in data["extra_models"]] == (
        ["demo"] if action == "add" else []
    )
    assert not (manager.custom_path / "example.json").exists()
    restored = managers.ProviderManager().saved_plugin_provider_infos()[
        "example"
    ]
    assert [model.id for model in restored.extra_models] == (
        ["demo"] if action == "add" else []
    )


def test_selected_app_lists_and_activates_stored_models(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from qwenpaw.app.routers.providers import router
    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli
    from qwenpaw.providers.provider_manager import ProviderManager

    remote = ProviderManager()
    provider = remote.get_provider("deepseek")
    first, second = provider.models[:2]
    provider.api_key = "example-provider-key"
    remote.builtin_providers = {provider.id: provider}
    snapshot = ProviderInfo(
        id="unavailable",
        name="Unavailable",
        api_key="retained-key",
    )
    (remote.plugin_path / "unavailable.json").write_text(
        snapshot.model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(remote, "maybe_probe_multimodal", lambda *args: None)
    monkeypatch.setattr(
        pcmd,
        "_manager",
        lambda: pytest.fail("read local profile"),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.provider_manager = remote
    monkeypatch.setattr(
        http,
        "client",
        lambda url: TestClient(app, base_url=url + "/api/"),
    )

    with TestClient(app) as client:
        assert client.get("/api/models").json()[0]["models"] == []
        unavailable = client.get("/api/models", params={"view": "unavailable"})
        assert unavailable.json()[0]["api_key"] == "******"
        url = "/api/models/deepseek/models"
        model = {"id": "custom-model", "name": "Custom"}
        assert client.post(url, json=model).status_code == 201
        rejected = client.post(url, json=model)
        assert rejected.status_code == 409
        assert "already exists" in rejected.json()["detail"]

    def choose(prompt, options, default):
        if prompt == "Select LLM model:":
            assert first.name in options
            return second.name
        return options[0]

    monkeypatch.setattr(pcmd, "prompt_choice", choose)
    runner = CliRunner()
    args = ["--host", "selected", "models"]
    selected = runner.invoke(cli, [*args, "set-llm"])
    assert selected.exit_code == 0, (selected.output, selected.exception)
    assert remote.get_active_model().model == second.id
    listed = runner.invoke(cli, [*args, "list"])
    assert listed.exit_code == 0, (listed.output, listed.exception)
    assert f"{provider.id} / {second.id}" in listed.output
    assert f"{first.name} ({first.id})" in listed.output
    assert "Unavailable (unavailable) [plugin unavailable]" in listed.output
    assert (
        provider.api_key not in listed.output
        and snapshot.api_key not in listed.output
    )


@pytest.mark.parametrize(
    "status,detail,expected_exit",
    [
        (409, "Model 'one' already exists", 0),
        (404, "Model 'one' already exists", 0),
        (404, "Model 'one' cannot be added: permission_denied", 0),
        (404, "Provider 'example' not found", 1),
        (503, "Service unavailable", 1),
    ],
)
def test_add_model_wizard_only_retries_model_conflicts(
    monkeypatch,
    status,
    detail,
    expected_exit,
):
    import httpx
    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli

    provider = ProviderInfo(
        id="example",
        name="Example",
        base_url="http://example",
        require_api_key=False,
        models=[ModelInfo(id="one", name="One")],
    )

    def respond(request):
        if request.method == "POST":
            return httpx.Response(status, json={"detail": detail})
        if request.url.path.endswith("/active"):
            return httpx.Response(200, json={"active_llm": None})
        return httpx.Response(
            200,
            json=(
                [provider.model_dump()]
                if request.url.path.endswith("/models")
                else provider.model_dump()
            ),
        )

    monkeypatch.setattr(
        http,
        "client",
        lambda url: httpx.Client(
            base_url=url + "/api/",
            transport=httpx.MockTransport(respond),
        ),
    )
    monkeypatch.setattr(
        pcmd,
        "prompt_choice",
        lambda prompt, options, default: options[0],
    )
    result = CliRunner().invoke(
        cli,
        ["--host", "selected", "models", "config"],
        input="\ny\none\nOne\nn\nn\n",
    )
    assert result.exit_code == expected_exit, result.output
    if expected_exit == 0:
        assert detail in result.output
        assert "LLM: Example / one" in result.output
    else:
        assert "Cannot access provider" in result.output


@pytest.mark.parametrize(
    "server,target",
    [
        ("same", "app"),
        ("other-working", "disk"),
        ("other-secrets", "disk"),
        ("old", "disk"),
        ("offline", "disk"),
        ("sign-in", "disk"),
    ],
)
def test_implicit_provider_write_verifies_the_recorded_app(
    monkeypatch,
    tmp_path,
    manager,
    server,
    target,
):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from qwenpaw import constant
    from qwenpaw.app._app import get_version
    from qwenpaw.cli import http
    from qwenpaw.cli.main import cli
    from qwenpaw.config import utils
    from qwenpaw.utils.runtime_api import PROFILE_PROBE_HEADER

    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)
    monkeypatch.setattr(utils, "read_last_api", lambda: ("127.0.0.1", 8123))
    monkeypatch.setattr(constant, "WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr(constant, "SECRET_DIR", tmp_path / "secret")
    app = FastAPI()
    app.get("/api/version")(get_version)
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/version":
            if server == "offline":
                raise httpx.ConnectError("not listening", request=request)
            if server == "old":
                return httpx.Response(200, json={"version": "old"})
            with monkeypatch.context() as profile, TestClient(app) as backend:
                if server == "other-working":
                    profile.setattr(
                        constant,
                        "WORKING_DIR",
                        tmp_path / "other",
                    )
                if server == "other-secrets":
                    profile.setattr(constant, "SECRET_DIR", tmp_path / "other")
                response = backend.get(
                    "/api/version",
                    headers={
                        PROFILE_PROBE_HEADER: request.headers[
                            PROFILE_PROBE_HEADER
                        ],
                    },
                )
                assert set(response.json()) == {"version"}
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    json=response.json(),
                )
        if request.method == "GET":
            return httpx.Response(401 if server == "sign-in" else 200)
        assert server == "same"
        return httpx.Response(201, json={"id": "new", "name": "New"})

    monkeypatch.setattr(
        http,
        "api_client",
        lambda url, **options: httpx.Client(
            base_url=url,
            transport=httpx.MockTransport(respond),
        ),
    )
    result = CliRunner().invoke(
        cli,
        ["models", "add-provider", "new", "-n", "New"],
    )
    assert result.exit_code == 0, result.output
    assert ("new" in manager._providers) == (target == "disk")
    expected = [("GET", "/api/version")]
    if server in {"same", "sign-in"}:
        expected.append(("GET", "/api/models"))
    if target == "app":
        expected.append(("POST", "/api/models/custom-providers"))
    assert requests == expected
