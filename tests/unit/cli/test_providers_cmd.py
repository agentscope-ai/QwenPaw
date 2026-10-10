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

    def _save_provider(self, provider, is_builtin=False):
        self.saved.append(provider.id)


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


class TestSaveProvider:
    def test_missing_provider_ignored(self, manager):
        pcmd._save_provider(manager, "ghost")
        assert manager.saved == []

    def test_saves_builtin_flag(self, manager):
        manager._providers["builtin-one"] = FakeProvider("builtin-one")
        pcmd._save_provider(manager, "builtin-one")
        assert manager.saved == ["builtin-one"]


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


class TestWaitForLocalModelDownload:
    def test_returns_on_terminal_status(self, monkeypatch):
        calls = {"n": 0}

        class M:
            def get_model_download_progress(self):
                calls["n"] += 1
                if calls["n"] < 3:
                    return {"status": "downloading"}
                return {"status": "completed", "local_path": "/m"}

        monkeypatch.setattr(pcmd.time, "sleep", lambda s: None)
        got = pcmd._wait_for_local_model_download(M())
        assert got["status"] == "completed"

    def test_timeout_cancels_and_raises(self, monkeypatch):
        cancelled = []

        class M:
            def get_model_download_progress(self):
                return {"status": "downloading"}

            def cancel_model_download(self):
                cancelled.append(True)

        monkeypatch.setattr(pcmd.time, "sleep", lambda s: None)
        with pytest.raises(click.ClickException, match="Timed out"):
            pcmd._wait_for_local_model_download(M(), timeout=0)
        assert cancelled == [True]

    def test_timeout_without_cancel_method(self, monkeypatch):
        class M:
            def get_model_download_progress(self):
                return {"status": "downloading"}

        monkeypatch.setattr(pcmd.time, "sleep", lambda s: None)
        with pytest.raises(click.ClickException, match="Timed out"):
            pcmd._wait_for_local_model_download(M(), timeout=0)

    def test_keyboard_interrupt_cancels_and_aborts(self, monkeypatch):
        cancelled = []

        class M:
            def get_model_download_progress(self):
                raise KeyboardInterrupt

            def cancel_model_download(self):
                cancelled.append(True)

        with pytest.raises(click.Abort):
            pcmd._wait_for_local_model_download(M())
        assert cancelled == [True]


class TestGetLocalModelManager:
    def test_missing_dependency_exits(self, monkeypatch):
        # `from ..local_models import ...` on a module set to None in
        # sys.modules raises ImportError -> the CLI prints and exits 1
        import sys

        monkeypatch.setitem(sys.modules, "qwenpaw.local_models", None)
        with pytest.raises(SystemExit) as exc:
            pcmd._get_local_model_manager()
        assert exc.value.code == 1

    def test_returns_singleton(self, monkeypatch):
        sentinel = object()

        class LM:
            @staticmethod
            def get_instance():
                return sentinel

        import types

        fake = types.ModuleType("qwenpaw.local_models")
        fake.LocalModelManager = LM
        import sys

        monkeypatch.setitem(sys.modules, "qwenpaw.local_models", fake)
        assert pcmd._get_local_model_manager() is sentinel


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
        # base_url=None means "keep existing"
        assert manager.updated[-1][1]["base_url"] is None

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
            pcmd._add_models_interactive("ghost")

    def test_ollama_returns_immediately(self, manager):
        manager._providers["ollama"] = FakeProvider("ollama")
        pcmd._add_models_interactive("ollama")  # no prompts -> returns

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
        pcmd._add_models_interactive("p1")
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
        pcmd._add_models_interactive("p1")
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
        pcmd._add_models_interactive("p1")
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
        pcmd._add_models_interactive("p1")  # must not raise


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
            "configure_provider_api_key_interactive",
            lambda provider_id=None: "p1",
        )
        monkeypatch.setattr(pcmd, "_add_models_interactive", lambda pid: None)
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
            "configure_llm_slot_interactive",
            lambda use_defaults=False: seen.append(use_defaults),
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
            "configure_provider_api_key_interactive",
            lambda provider_id=None: "qwenpaw-local",
        )
        monkeypatch.setattr(
            pcmd,
            "configure_llm_slot_interactive",
            lambda use_defaults=False: activated.append(True),
        )
        pcmd.configure_providers_interactive()
        assert activated == [True]

    def test_unknown_provider_after_config_exits(self, manager, monkeypatch):
        monkeypatch.setattr(
            pcmd,
            "configure_provider_api_key_interactive",
            lambda provider_id=None: "ghost",
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
            "configure_provider_api_key_interactive",
            lambda provider_id=None: "p1",
        )
        added = []
        monkeypatch.setattr(
            pcmd,
            "_add_models_interactive",
            lambda pid: added.append(pid),
        )
        monkeypatch.setattr(pcmd.click, "confirm", lambda *a, **kw: False)
        activated = []
        monkeypatch.setattr(
            pcmd,
            "configure_llm_slot_interactive",
            lambda use_defaults=False: activated.append(True),
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
        assert "No models downloaded." in res.output
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
        assert res.exit_code == 0
        assert "not found" in res.output


# ---------------------------------------------------------------------------
# local model commands
# ---------------------------------------------------------------------------


class _LocalMgr:
    def __init__(self):
        self.progress_seq = [
            {"status": "downloading"},
            {
                "status": "completed",
                "local_path": "/m",
                "downloaded_bytes": 5 * 1024 * 1024,
            },
        ]
        self.started = []
        self.cancelled = []
        self.removed = []

    def start_model_download(self, repo_id, source=None):
        self.started.append((repo_id, source))

    def get_model_download_progress(self):
        return self.progress_seq.pop(0)

    def cancel_model_download(self):
        self.cancelled.append(True)

    def list_downloaded_models(self):
        return []

    def remove_downloaded_model(self, model_id):
        if model_id == "boom":
            raise ValueError("cannot remove")
        self.removed.append(model_id)


@pytest.fixture()
def local_mgr(monkeypatch):
    m = _LocalMgr()
    monkeypatch.setattr(pcmd, "_get_local_model_manager", lambda: m)
    return m


class TestDownloadCmd:
    def test_file_option_rejected(self, local_mgr):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["download", "org/repo", "--file", "x.gguf"],
        )
        assert res.exit_code == 1
        assert "--file is no longer supported" in res.output

    def test_download_completed(self, local_mgr, monkeypatch):
        monkeypatch.setattr(pcmd.time, "sleep", lambda s: None)
        res = CliRunner().invoke(
            pcmd.models_group,
            ["download", "org/repo", "-s", "modelscope"],
        )
        assert res.exit_code == 0
        assert "Done! Model saved to: /m" in res.output
        assert "Size: 5.0 MB" in res.output
        assert local_mgr.started[0][1].value == "modelscope"

    def test_download_failed_status(self, local_mgr, monkeypatch):
        local_mgr.progress_seq = [
            {"status": "failed", "error": "disk full"},
        ]
        monkeypatch.setattr(pcmd.time, "sleep", lambda s: None)
        res = CliRunner().invoke(pcmd.models_group, ["download", "org/repo"])
        assert res.exit_code == 1
        assert "disk full" in res.output

    def test_download_start_raises(self, local_mgr):
        def boom(repo, source=None):
            raise RuntimeError("no disk")

        local_mgr.start_model_download = boom
        res = CliRunner().invoke(pcmd.models_group, ["download", "org/repo"])
        assert res.exit_code == 1
        assert "Download failed" in res.output


class TestListLocalCmd:
    def test_empty(self, local_mgr):
        res = CliRunner().invoke(pcmd.models_group, ["local"])
        assert res.exit_code == 0
        assert "No local models downloaded" in res.output

    def test_lists_models(self, local_mgr):
        local_mgr.list_downloaded_models = lambda: [
            SimpleNamespace(
                name="Tiny",
                id="tiny",
                size_bytes=2 * 1024 * 1024,
            ),
        ]
        res = CliRunner().invoke(pcmd.models_group, ["local"])
        assert res.exit_code == 0
        assert "Tiny" in res.output
        assert "2.0 MB" in res.output


class TestRemoveLocalCmd:
    def test_declined(self, local_mgr):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-local", "m1"],
            input="n\n",
        )
        assert res.exit_code == 0
        assert local_mgr.removed == []

    def test_removed(self, local_mgr):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-local", "m1", "-y"],
        )
        assert res.exit_code == 0
        assert local_mgr.removed == ["m1"]

    def test_error(self, local_mgr):
        res = CliRunner().invoke(
            pcmd.models_group,
            ["remove-local", "boom", "-y"],
        )
        assert res.exit_code == 1
        assert "cannot remove" in res.output


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
