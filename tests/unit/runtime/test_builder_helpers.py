# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for the module-level helpers in runtime/builder.py.

These three helpers are pure (no I/O beyond an injected language preference),
so they are tested directly; AgentBuilder itself needs the full runtime and is
covered elsewhere.
"""

import types

import pytest

from qwenpaw.runtime import builder as builder_mod


# ── _resolve_react_iterations ─────────────────────────────────────────


class TestResolveReactIterations:
    def test_plain_chat_request_keeps_the_configured_limit(self):
        assert builder_mod._resolve_react_iterations(25, {}) == 25

    def test_non_portability_source_ignores_a_larger_request(self):
        ctx = {"source": "chat", "max_react_iterations": 9999}
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_portability_source_may_outgrow_the_limit(self):
        ctx = {"source": "portability_adaptation", "max_react_iterations": 200}
        assert builder_mod._resolve_react_iterations(25, ctx) == 200

    def test_portability_request_below_configured_keeps_configured(self):
        """max(configured, ...) means a smaller request cannot shrink."""
        ctx = {"source": "portability_adaptation", "max_react_iterations": 5}
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_portability_request_is_capped_at_the_hard_ceiling(self):
        ctx = {
            "source": "portability_adaptation",
            "max_react_iterations": 999_999,
        }
        assert (
            builder_mod._resolve_react_iterations(25, ctx)
            == builder_mod._PORTABILITY_MAX_ITERS
        )

    def test_hard_ceiling_value(self):
        assert builder_mod._PORTABILITY_MAX_ITERS == 4000

    def test_bool_request_is_rejected_even_though_bool_is_an_int(self):
        """True == 1 here, so the isinstance(bool) guard is load-bearing."""
        ctx = {
            "source": "portability_adaptation",
            "max_react_iterations": True,
        }
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_float_request_is_rejected(self):
        ctx = {
            "source": "portability_adaptation",
            "max_react_iterations": 200.0,
        }
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_string_request_is_rejected(self):
        ctx = {
            "source": "portability_adaptation",
            "max_react_iterations": "200",
        }
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_zero_request_is_rejected(self):
        ctx = {"source": "portability_adaptation", "max_react_iterations": 0}
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_negative_request_is_rejected(self):
        ctx = {"source": "portability_adaptation", "max_react_iterations": -5}
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_missing_request_key_keeps_configured(self):
        ctx = {"source": "portability_adaptation"}
        assert builder_mod._resolve_react_iterations(25, ctx) == 25

    def test_none_request_keeps_configured(self):
        ctx = {
            "source": "portability_adaptation",
            "max_react_iterations": None,
        }
        assert builder_mod._resolve_react_iterations(25, ctx) == 25


# ── _descriptor_for ───────────────────────────────────────────────────


class TestDescriptorFor:
    def test_reads_the_descriptor_off_the_tool_itself(self):
        sentinel = object()
        tool = types.SimpleNamespace(_tool_descriptor=sentinel)
        assert builder_mod._descriptor_for(tool) is sentinel

    def test_reads_the_descriptor_off_func(self):
        sentinel = object()
        tool = types.SimpleNamespace(
            _tool_descriptor=None,
            func=types.SimpleNamespace(_tool_descriptor=sentinel),
        )
        assert builder_mod._descriptor_for(tool) is sentinel

    def test_reads_the_descriptor_off_private_func(self):
        sentinel = object()
        tool = types.SimpleNamespace(
            _tool_descriptor=None,
            func=None,
            _func=types.SimpleNamespace(_tool_descriptor=sentinel),
        )
        assert builder_mod._descriptor_for(tool) is sentinel

    def test_direct_descriptor_wins_over_wrapped_ones(self):
        """The candidate order is tool, func, _func - first hit wins."""
        direct = object()
        wrapped = object()
        tool = types.SimpleNamespace(
            _tool_descriptor=direct,
            func=types.SimpleNamespace(_tool_descriptor=wrapped),
        )
        assert builder_mod._descriptor_for(tool) is direct

    def test_returns_none_when_no_descriptor_anywhere(self):
        tool = types.SimpleNamespace(func=object(), _func=object())
        assert builder_mod._descriptor_for(tool) is None

    def test_returns_none_for_a_bare_object(self):
        assert builder_mod._descriptor_for(object()) is None

    def test_tolerates_missing_wrapper_attributes(self):
        tool = types.SimpleNamespace()  # no func, no _func, no descriptor
        assert builder_mod._descriptor_for(tool) is None


# ── _bound_skill_loader_dirs ─────────────────────────────────────────


def _tool_with_metadata(metadata):
    """A tool whose descriptor carries the given metadata dict."""
    descriptor = types.SimpleNamespace(metadata=metadata)
    return types.SimpleNamespace(_tool_descriptor=descriptor)


@pytest.fixture()
def zh_language(monkeypatch):
    """Pin the builtin skill language preference to 'zh'."""
    from qwenpaw.agents.skill_system import registry

    monkeypatch.setattr(
        registry,
        "get_builtin_skill_language_preference",
        lambda: "zh",
    )
    return "zh"


class TestBoundSkillLoaderDirs:
    def test_empty_tools_yield_no_dirs(self, zh_language):
        assert builder_mod._bound_skill_loader_dirs([]) == []

    def test_tool_without_a_descriptor_is_skipped(self, zh_language):
        assert builder_mod._bound_skill_loader_dirs([object()]) == []

    def test_descriptor_without_metadata_is_skipped(self, zh_language):
        tool = types.SimpleNamespace(_tool_descriptor=types.SimpleNamespace())
        assert builder_mod._bound_skill_loader_dirs([tool]) == []

    def test_metadata_without_bound_skills_is_skipped(
        self,
        zh_language,
        tmp_path,
    ):
        tool = _tool_with_metadata({"bound_skills_root": str(tmp_path)})
        assert builder_mod._bound_skill_loader_dirs([tool]) == []

    def test_metadata_without_root_is_skipped(self, zh_language):
        tool = _tool_with_metadata({"bound_skills": ("alpha",)})
        assert builder_mod._bound_skill_loader_dirs([tool]) == []

    def test_returns_the_preferred_language_dir(self, zh_language, tmp_path):
        skill = tmp_path / "alpha-zh"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# zh", encoding="utf-8")
        tool = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [str(skill)]

    def test_falls_back_to_en_when_preferred_language_missing(
        self,
        zh_language,
        tmp_path,
    ):
        skill = tmp_path / "alpha-en"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# en", encoding="utf-8")
        tool = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [str(skill)]

    def test_prefers_language_variant_over_en(self, zh_language, tmp_path):
        (tmp_path / "alpha-en").mkdir()
        (tmp_path / "alpha-en" / "SKILL.md").write_text("en", encoding="utf-8")
        zh = tmp_path / "alpha-zh"
        zh.mkdir()
        (zh / "SKILL.md").write_text("zh", encoding="utf-8")
        tool = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [str(zh)]

    def test_dir_without_skill_md_is_not_injected(self, zh_language, tmp_path):
        (tmp_path / "alpha-zh").mkdir()  # exists but has no SKILL.md
        tool = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == []

    def test_multiple_names_keep_order(self, zh_language, tmp_path):
        for name in ("alpha", "beta"):
            d = tmp_path / f"{name}-zh"
            d.mkdir()
            (d / "SKILL.md").write_text("#", encoding="utf-8")
        tool = _tool_with_metadata(
            {
                "bound_skills": ("alpha", "beta"),
                "bound_skills_root": str(tmp_path),
            },
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [
            str(tmp_path / "alpha-zh"),
            str(tmp_path / "beta-zh"),
        ]

    def test_one_valid_one_invalid_name_keeps_the_valid_one(
        self,
        zh_language,
        tmp_path,
    ):
        good = tmp_path / "alpha-zh"
        good.mkdir()
        (good / "SKILL.md").write_text("#", encoding="utf-8")
        # "beta" has neither beta-zh nor beta-en
        tool = _tool_with_metadata(
            {
                "bound_skills": ("alpha", "beta"),
                "bound_skills_root": str(tmp_path),
            },
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [str(good)]

    def test_aggregates_across_multiple_tools(self, zh_language, tmp_path):
        for name in ("alpha", "beta"):
            d = tmp_path / f"{name}-zh"
            d.mkdir()
            (d / "SKILL.md").write_text("#", encoding="utf-8")
        tool_a = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )
        tool_b = _tool_with_metadata(
            {"bound_skills": ("beta",), "bound_skills_root": str(tmp_path)},
        )

        assert builder_mod._bound_skill_loader_dirs([tool_a, tool_b]) == [
            str(tmp_path / "alpha-zh"),
            str(tmp_path / "beta-zh"),
        ]

    def test_missing_skill_logs_a_warning(self, zh_language, tmp_path, caplog):
        import logging

        tool = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )
        with caplog.at_level(logging.WARNING):
            builder_mod._bound_skill_loader_dirs([tool])

        assert "bound skill" in caplog.text
        assert "alpha" in caplog.text

    def test_honours_a_different_language_preference(
        self,
        monkeypatch,
        tmp_path,
    ):
        from qwenpaw.agents.skill_system import registry

        monkeypatch.setattr(
            registry,
            "get_builtin_skill_language_preference",
            lambda: "ru",
        )
        skill = tmp_path / "alpha-ru"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# ru", encoding="utf-8")
        tool = _tool_with_metadata(
            {"bound_skills": ("alpha",), "bound_skills_root": str(tmp_path)},
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [str(skill)]

    def test_descriptor_via_func_wrapper_is_found(self, zh_language, tmp_path):
        skill = tmp_path / "alpha-zh"
        skill.mkdir()
        (skill / "SKILL.md").write_text("#", encoding="utf-8")
        descriptor = types.SimpleNamespace(
            metadata={
                "bound_skills": ("alpha",),
                "bound_skills_root": str(tmp_path),
            },
        )
        # Descriptor reached through .func, not the tool itself.
        tool = types.SimpleNamespace(
            _tool_descriptor=None,
            func=types.SimpleNamespace(_tool_descriptor=descriptor),
        )

        assert builder_mod._bound_skill_loader_dirs([tool]) == [str(skill)]
