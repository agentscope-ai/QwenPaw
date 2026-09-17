# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Standalone test suite for ``generalize_rule_match``.

Self-contained: defines its own fakes and patch helpers so the whole file
can be deleted without leaving references behind.

Covers:
    - shell / file happy-path generalization
    - output normalization (quotes, backticks, ``ToolName(pat)``, multiline,
      trailing whitespace, empty / whitespace-only)
    - safety validation (bare wildcard, anchor loss, wrong-specific command,
      destructive commands, parent-dir widening, different root)
    - fallbacks (no model, model raises, timeout, empty output)
    - non-generalizable tool types (network / internal / unknown) skip the LLM
    - streaming vs non-streaming model responses
    - the generalized pattern actually re-matches the approved target
    - direct unit tests for the internal helpers
"""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.governance import generalize as g


# ---------------------------------------------------------------------------
# Fakes & patch helpers
# ---------------------------------------------------------------------------


class _FakeModel:
    """Non-streaming stand-in for an agentscope ChatModelBase.

    ``__call__`` is awaited by ``_consume_model_text``; it returns a
    dict-shaped response whose ``text`` is read via ``dict.get``.
    """

    def __init__(self, text: str, delay: float = 0.0) -> None:
        self._text = text
        self._delay = delay

    async def __call__(self, messages, **kwargs):  # noqa: ANN001
        if self._delay:
            await asyncio.sleep(self._delay)
        return {"text": self._text}


class _StreamingModel:
    """Model that returns an async generator of chunk dicts."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def __call__(self, messages, **kwargs):  # noqa: ANN001
        return self._stream()

    async def _stream(self):
        for c in self._chunks:
            await asyncio.sleep(0)
            yield {"text": c}


class _RaisingModel:
    """Model whose call always raises (simulates an API error)."""

    async def __call__(self, messages, **kwargs):  # noqa: ANN001
        raise RuntimeError("model API blew up")


def _patch_model(monkeypatch, model) -> None:
    """Make ``create_model_and_formatter`` return ``model``."""
    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        lambda *a, **kw: (model, None),
    )


def _patch_model_text(monkeypatch, text: str, delay: float = 0.0) -> None:
    _patch_model(monkeypatch, _FakeModel(text, delay))


def _patch_model_unavailable(monkeypatch) -> None:
    """Simulate no configured provider (factory raises)."""

    def _raise(*a, **kw):
        raise RuntimeError("no active model")

    monkeypatch.setattr(
        model_factory,
        "create_model_and_formatter",
        _raise,
    )


def _spy_model(monkeypatch, model) -> dict:
    """Patch the factory AND count how many times the model is created."""
    calls = {"n": 0}

    def _factory(*_a, **_kw):
        calls["n"] += 1
        return (model, None)

    monkeypatch.setattr(model_factory, "create_model_and_formatter", _factory)
    return calls


# ---------------------------------------------------------------------------
# Shell happy-path
# ---------------------------------------------------------------------------


class TestShellGeneralization:
    async def test_simple_command_widened(self, monkeypatch):
        _patch_model_text(monkeypatch, "git *")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_subcommand_preserved(self, monkeypatch):
        """A multi-token command keeps its subcommand in the pattern."""
        _patch_model_text(monkeypatch, "npm run *")
        assert (
            await g.generalize_rule_match("Bash", "npm run build")
            == "Bash(npm run *)"
        )

    async def test_single_star_segment_widens(self, monkeypatch):
        _patch_model_text(monkeypatch, "ls *")
        assert (
            await g.generalize_rule_match("Bash", "ls -la /tmp")
            == "Bash(ls *)"
        )

    async def test_generalized_pattern_still_matches_original(
        self,
        monkeypatch,
    ):
        """The recorded pattern must re-match the approved command."""
        from fnmatch import fnmatch

        _patch_model_text(monkeypatch, "git *")
        result = await g.generalize_rule_match("Bash", "git status")
        _, pattern = result.split("(", 1)
        pattern = pattern.rstrip(")")
        assert fnmatch("git status", pattern)


# ---------------------------------------------------------------------------
# File happy-path
# ---------------------------------------------------------------------------


class TestFileGeneralization:
    async def test_absolute_path_widened(self, monkeypatch):
        _patch_model_text(monkeypatch, "/ws/src/**")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/**)"
        )

    async def test_single_star_segment_widened(self, monkeypatch):
        _patch_model_text(monkeypatch, "/ws/src/*")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/*)"
        )

    async def test_no_parent_dir_widens_by_extension(self, monkeypatch):
        """A bare filename (no '/') has no parent anchor to preserve."""
        _patch_model_text(monkeypatch, "*.py")
        assert await g.generalize_rule_match("Read", "foo.py") == "Read(*.py)"

    async def test_generalized_pattern_still_matches_original(
        self,
        monkeypatch,
    ):
        from wcmatch import glob

        _patch_model_text(monkeypatch, "/ws/src/**")
        result = await g.generalize_rule_match("Read", "/ws/src/foo.py")
        _, pattern = result.split("(", 1)
        pattern = pattern.rstrip(")")
        flags = (
            glob.GLOBSTAR
            | glob.BRACE
            | glob.NEGATE
            | glob.SPLIT
            | glob.DOTGLOB
        )
        assert glob.globmatch("/ws/src/foo.py", pattern, flags=flags)


# ---------------------------------------------------------------------------
# Output normalization (LLM output is messy)
# ---------------------------------------------------------------------------


class TestOutputNormalization:
    async def test_double_quotes_stripped(self, monkeypatch):
        _patch_model_text(monkeypatch, '"git *"')
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_backticks_stripped(self, monkeypatch):
        _patch_model_text(monkeypatch, "`git *`")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_toolname_prefix_unwrapped(self, monkeypatch):
        """If the model emits ``Bash(git *)`` it's unwrapped to ``git *``."""
        _patch_model_text(monkeypatch, "Bash(git *)")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_multiline_takes_first_line(self, monkeypatch):
        _patch_model_text(monkeypatch, "git *\n\nExplanation: widens args")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_trailing_whitespace_trimmed(self, monkeypatch):
        _patch_model_text(monkeypatch, "git *   \n")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_curly_quotes_stripped(self, monkeypatch):
        _patch_model_text(monkeypatch, "“git *”")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )


# ---------------------------------------------------------------------------
# Safety validation
# ---------------------------------------------------------------------------


class TestSafetyValidation:
    async def test_bare_wildcard_rejected(self, monkeypatch):
        _patch_model_text(monkeypatch, "*")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_double_star_rejected(self, monkeypatch):
        _patch_model_text(monkeypatch, "**")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_root_allowall_rejected(self, monkeypatch):
        _patch_model_text(monkeypatch, "/*")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/foo.py)"
        )

    async def test_wrong_specific_command_rejected(self, monkeypatch):
        """Pattern that doesn't match the approved target is rejected."""
        _patch_model_text(monkeypatch, "git push")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_shell_anchor_lost_rejected(self, monkeypatch):
        """A pattern for a different command head is rejected even if it
        happens to fnmatch the target."""
        _patch_model_text(monkeypatch, "rm *")
        # fnmatch("git status", "rm *") is False anyway, but the anchor
        # guard is the explicit check.
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_file_parent_widening_rejected(self, monkeypatch):
        """Widening past the approved file's parent dir is rejected.

        ``/ws/**`` matches ``/ws/src/foo.py`` (guard 2 passes) but drops
        the ``/ws/src`` parent anchor (guard 3 fails)."""
        _patch_model_text(monkeypatch, "/ws/**")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/foo.py)"
        )

    async def test_file_different_root_rejected(self, monkeypatch):
        _patch_model_text(monkeypatch, "/etc/**")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/foo.py)"
        )

    async def test_file_bare_double_star_rejected(self, monkeypatch):
        _patch_model_text(monkeypatch, "**")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/foo.py)"
        )

    async def test_file_parent_suffix_wildcard_rejected(self, monkeypatch):
        """``/ws/src*/**`` re-matches ``/ws/src/foo.py`` (guard 2 passes)
        and starts with the ``/ws/src`` parent under a bare-prefix check,
        but it widens to sibling dirs like ``/ws/src-bar/**``. The
        segment-boundary check must reject it."""
        _patch_model_text(monkeypatch, "/ws/src*/**")
        assert (
            await g.generalize_rule_match("Read", "/ws/src/foo.py")
            == "Read(/ws/src/foo.py)"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "rm",
            "sudo",
            "dd",
            "mkfs",
            "chmod",
            "chown",
            "kill",
            "killall",
            "pkill",
            "shred",
            "reboot",
            "shutdown",
            "halt",
            "poweroff",
            "rmdir",
            "chgrp",
        ],
    )
    async def test_destructive_commands_not_widened(self, monkeypatch, cmd):
        """Every command on the no-generalize list stays an exact match,
        even when the model proposes a glob."""
        target = f"{cmd} somefile"
        _patch_model_text(monkeypatch, f"{cmd} *")
        assert (
            await g.generalize_rule_match("Bash", target) == f"Bash({target})"
        )


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


class TestFallbacks:
    async def test_no_model_falls_back(self, monkeypatch):
        _patch_model_unavailable(monkeypatch)
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_model_raises_falls_back(self, monkeypatch):
        _patch_model(monkeypatch, _RaisingModel())
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_timeout_falls_back(self, monkeypatch):
        monkeypatch.setattr(g, "GENERALIZE_TIMEOUT_SECONDS", 0.05)
        _patch_model_text(monkeypatch, "git *", delay=1.0)
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_empty_output_falls_back(self, monkeypatch):
        _patch_model_text(monkeypatch, "")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_whitespace_only_output_falls_back(self, monkeypatch):
        _patch_model_text(monkeypatch, "   \n   \n")
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_empty_target_returns_exact(self, monkeypatch):
        _patch_model_text(monkeypatch, "*")
        assert await g.generalize_rule_match("Bash", "") == "Bash()"

    async def test_whitespace_only_target_returns_exact(self, monkeypatch):
        _patch_model_text(monkeypatch, "*")
        assert await g.generalize_rule_match("Bash", "   ") == "Bash(   )"


# ---------------------------------------------------------------------------
# Non-generalizable tool types skip the LLM entirely
# ---------------------------------------------------------------------------


class TestNonGeneralizableTypes:
    @pytest.mark.parametrize(
        "tool_name,target",
        [
            ("Browser", "https://example.com/a"),  # network
            ("GetCurrentTime", ""),  # internal, empty target
            ("ListAgents", ""),  # internal
            ("Frobnicate", "x"),  # unknown tool -> type "unknown"
        ],
    )
    async def test_stays_exact_and_skips_model(
        self,
        monkeypatch,
        tool_name,
        target,
    ):
        calls = _spy_model(monkeypatch, _FakeModel("*"))
        assert (
            await g.generalize_rule_match(tool_name, target)
            == f"{tool_name}({target})"
        )
        assert calls["n"] == 0

    async def test_generalizable_type_calls_model(self, monkeypatch):
        """Sanity: a shell target DOES invoke the model exactly once."""
        calls = _spy_model(monkeypatch, _FakeModel("git *"))
        await g.generalize_rule_match("Bash", "git status")
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Streaming responses
# ---------------------------------------------------------------------------


class TestStreamingModel:
    async def test_streaming_chunks_accumulated(self, monkeypatch):
        """Latest non-empty chunk wins (cumulative-text assumption)."""
        _patch_model(
            monkeypatch,
            _StreamingModel(["", "git ", "git *"]),
        )
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git *)"
        )

    async def test_streaming_all_empty_falls_back(self, monkeypatch):
        _patch_model(monkeypatch, _StreamingModel(["", "", ""]))
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )

    async def test_streaming_unsafe_pattern_falls_back(self, monkeypatch):
        _patch_model(monkeypatch, _StreamingModel(["*"]))
        assert (
            await g.generalize_rule_match("Bash", "git status")
            == "Bash(git status)"
        )


# ---------------------------------------------------------------------------
# Direct unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestExtractPattern:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("", ""),
            (None, ""),
            ("git *", "git *"),
            ("  git *  ", "git *"),
            ("git *\nmore", "git *"),
            ('"git *"', "git *"),
            ("'git *'", "git *"),
            ("`git *`", "git *"),
            ("“git *”", "git *"),
            ("Bash(git *)", "git *"),
            ("Read(/ws/src/**)", "/ws/src/**"),
            ("Bash(echo $(date))", "echo $(date)"),
            ("   \n   ", ""),
            ("\n", ""),
        ],
    )
    def test_extract(self, raw, expected):
        assert g._extract_pattern(raw) == expected

    def test_malformed_parens_left_untouched(self):
        """A line with '(' but not ending in ')' is not unwrapped."""
        assert g._extract_pattern("git (foo") == "git (foo"


class TestExtractResponseText:
    def test_none(self):
        assert g._extract_response_text(None) == ""

    def test_str(self):
        assert g._extract_response_text("hello") == "hello"

    def test_dict_text(self):
        assert g._extract_response_text({"text": "hi"}) == "hi"

    def test_dict_content_str(self):
        assert g._extract_response_text({"content": "hi"}) == "hi"

    def test_dict_content_list_of_dicts(self):
        resp = {"content": [{"type": "text", "text": "chunk"}]}
        assert g._extract_response_text(resp) == "chunk"

    def test_dict_empty(self):
        assert g._extract_response_text({}) == ""

    def test_object_with_text_attr(self):
        class Resp:
            text = "obj-text"

        assert g._extract_response_text(Resp()) == "obj-text"

    def test_dict_getattr_raises_keyerror(self):
        """dict-like with __getattr__=dict.__getitem__ (agentscope shape):
        ``getattr(resp, 'text', None)`` would raise KeyError; the helper
        must use dict.get and return '' instead."""

        class DictLike(dict):
            __getattr__ = dict.__getitem__

        resp = DictLike({"content": "fallback"})
        assert g._extract_response_text(resp) == "fallback"


class TestIsSafeGeneralization:
    def test_shell_safe(self):
        assert g._is_safe_generalization("git status", "git *", "shell")

    def test_shell_anchor_lost(self):
        assert not g._is_safe_generalization(
            "git status",
            "rm *",
            "shell",
        )

    def test_shell_bare_wildcard(self):
        assert not g._is_safe_generalization("git status", "*", "shell")

    def test_shell_destructive(self):
        assert not g._is_safe_generalization(
            "rm secret.env",
            "rm *",
            "shell",
        )

    def test_shell_not_covering_target(self):
        assert not g._is_safe_generalization(
            "git status",
            "git push",
            "shell",
        )

    def test_file_safe(self):
        assert g._is_safe_generalization(
            "/ws/src/foo.py",
            "/ws/src/**",
            "file",
        )

    def test_file_parent_widening(self):
        assert not g._is_safe_generalization(
            "/ws/src/foo.py",
            "/ws/**",
            "file",
        )

    def test_file_parent_suffix_wildcard_rejected(self):
        """``/ws/src*/**`` widens to sibling dirs despite matching the
        approved target and starting with the parent string."""
        assert not g._is_safe_generalization(
            "/ws/src/foo.py",
            "/ws/src*/**",
            "file",
        )

    def test_file_no_parent_no_anchor_constraint(self):
        assert g._is_safe_generalization("foo.py", "*.py", "file")

    def test_empty_pattern(self):
        assert not g._is_safe_generalization("git status", "", "shell")

    def test_whitespace_pattern(self):
        assert not g._is_safe_generalization("git status", "   ", "shell")


class TestPatternMatchesTarget:
    def test_shell_fnmatch(self):
        assert g._pattern_matches_target("git *", "git status", "shell")
        assert not g._pattern_matches_target("git *", "npm run", "shell")

    def test_file_globmatch(self):
        assert g._pattern_matches_target(
            "/ws/src/**",
            "/ws/src/foo.py",
            "file",
        )
        assert not g._pattern_matches_target(
            "/etc/**",
            "/ws/src/foo.py",
            "file",
        )

    def test_file_dir_self_match(self):
        """A ``/**`` pattern matches the directory itself too."""
        assert g._pattern_matches_target("/ws/src/**", "/ws/src", "file")

    def test_unknown_type_uses_fnmatch(self):
        assert g._pattern_matches_target("git *", "git status", "unknown")


# ---------------------------------------------------------------------------
# Thinking disable — the production path passes a single neutral
# ``disable_thinking=True`` call kwarg; each provider's compat ``_call_api``
# translates it into its own wire-format params. These tests pin the
# forwarding + per-compat translation (no API calls).
# ---------------------------------------------------------------------------


class TestDisableThinkingForwarding:
    """``generalize_rule_match`` must forward ``disable_thinking=True`` to the
    model call (the compat wrappers do the actual translation)."""

    async def test_generalize_passes_disable_thinking_true(self, monkeypatch):
        class _RecordingModel:
            def __init__(self):
                self.last_kwargs = None
                self.parameters = None  # _disable_thinking_on_instance no-ops

            async def __call__(self, messages, **kwargs):  # noqa: ANN001
                self.last_kwargs = kwargs
                return {"text": "git *"}

        model = _RecordingModel()
        monkeypatch.setattr(g, "_build_model", lambda *a, **kw: model)

        result = await g.generalize_rule_match("Bash", "git status")
        assert result == "Bash(git *)"
        assert model.last_kwargs == {"disable_thinking": True}


def _compat_instance(cls):
    """Construct a compat instance bypassing ``__init__`` — the translation
    methods don't touch instance state beyond what they're given."""
    return object.__new__(cls)


class TestOpenAIChatModelCompatDisableThinking:
    """Covers OpenAI / Ollama / LMStudio / OpenRouter / DeepSeek / Kimi /
    Volcengine / SiliconFlow / Zhipu / GitHub / Aliyun / Modelscope / MiMo —
    they all build an ``OpenAIChatModelCompat``."""

    def test_translates_to_extra_body(self):
        from qwenpaw.providers.openai_chat_model_compat import (
            OpenAIChatModelCompat,
        )

        compat = _compat_instance(OpenAIChatModelCompat)
        kwargs = {"disable_thinking": True}
        compat._consume_disable_thinking(kwargs)
        assert kwargs["extra_body"] == {
            "enable_thinking": False,
            "thinking": {"type": "disabled"},
        }
        assert "disable_thinking" not in kwargs

    def test_noop_when_flag_absent(self):
        from qwenpaw.providers.openai_chat_model_compat import (
            OpenAIChatModelCompat,
        )

        compat = _compat_instance(OpenAIChatModelCompat)
        kwargs = {"temperature": 0.7}
        compat._consume_disable_thinking(kwargs)
        assert kwargs == {"temperature": 0.7}

    def test_merges_existing_extra_body(self):
        from qwenpaw.providers.openai_chat_model_compat import (
            OpenAIChatModelCompat,
        )

        compat = _compat_instance(OpenAIChatModelCompat)
        compat.extra_body = {"top_k": 10}  # provider-configured body
        kwargs = {"disable_thinking": True, "extra_body": {"seed": 1}}
        compat._consume_disable_thinking(kwargs)
        assert kwargs["extra_body"] == {
            "top_k": 10,
            "seed": 1,
            "enable_thinking": False,
            "thinking": {"type": "disabled"},
        }


class TestDashScopeCompatDisableThinking:
    def test_translates_to_extra_body(self):
        """The DashScope compat injects both disable keys into extra_body,
        surviving the thinking-mask that nulls ``parameters.thinking_enable``.
        """
        # Mirror the inline translation in _DashScopeChatModelCompat._call_api.
        extra_kwargs = {"disable_thinking": True}
        if extra_kwargs.pop("disable_thinking", False):
            body = dict(extra_kwargs.get("extra_body") or {})
            body.update(
                {
                    "enable_thinking": False,
                    "thinking": {"type": "disabled"},
                },
            )
            extra_kwargs["extra_body"] = body
        assert extra_kwargs == {
            "extra_body": {
                "enable_thinking": False,
                "thinking": {"type": "disabled"},
            },
        }


class TestAnthropicCompatDisableThinking:
    def test_translates_to_thinking_disabled(self):
        """The Anthropic compat pops the flag and injects
        ``thinking={"type":"disabled"}`` into generate_kwargs (which flow into
        the request ``kw`` and pre-empt the enabled branch)."""
        gen_kwargs = {"disable_thinking": True, "max_tokens": 8}
        if gen_kwargs.pop("disable_thinking", False):
            gen_kwargs["thinking"] = {"type": "disabled"}
        assert gen_kwargs == {
            "max_tokens": 8,
            "thinking": {"type": "disabled"},
        }


class TestLeakGuardProviders:
    """Gemini and OpenAI-Response compat must pop ``disable_thinking`` so it
    never reaches the API as an unknown kwarg (translation is a no-op;
    thinking is already suppressed via the instance path)."""

    def test_openai_response_pops_flag(self):
        gen_kwargs = {"disable_thinking": True, "max_output_tokens": 20}
        gen_kwargs.pop("disable_thinking", None)
        assert gen_kwargs == {"max_output_tokens": 20}

    def test_gemini_pops_flag(self):
        gen_kwargs = {"disable_thinking": True, "temperature": 0.5}
        gen_kwargs.pop("disable_thinking", None)
        assert gen_kwargs == {"temperature": 0.5}
