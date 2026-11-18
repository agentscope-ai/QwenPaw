# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for the current-context recall tool.

The module is pure apart from the ReMe in-memory index, which runs for real
here (verified: BM25Index + DefaultFileChunker import and retrieve without
file-backed start/reset/close). So the retrieval tests assert real ranking and
budget behaviour rather than mock call counts.
"""

import json

import pytest

from qwenpaw.agents.context.visual_compression.runtime import (
    recall_tool as rt,
)


# ── RecallRequestError ───────────────────────────────────────────────


class TestRecallRequestError:
    def test_carries_a_machine_readable_code(self):
        err = rt.RecallRequestError("invalid_query", "bad query")
        assert err.code == "invalid_query"
        assert str(err) == "bad query"

    def test_is_a_value_error(self):
        assert isinstance(rt.RecallRequestError("c", "m"), ValueError)


# ── serialize_result ────────────────────────────────────────────────


class TestSerializeResult:
    def test_shape_with_no_error(self):
        out = json.loads(rt.serialize_result([{"a": "b"}], "success"))
        assert out == {
            "status": "success",
            "results": [{"a": "b"}],
            "error": None,
        }

    def test_includes_the_error_object(self):
        out = json.loads(
            rt.serialize_result([], "error", {"code": "c", "message": "m"}),
        )
        assert out["error"] == {"code": "c", "message": "m"}
        assert out["status"] == "error"

    def test_writes_cjk_literally_not_escaped(self):
        raw = rt.serialize_result([{"passage": "中文"}], "success")
        assert "中文" in raw
        assert "\\u" not in raw

    def test_uses_compact_separators(self):
        """No whitespace after separators: the budget is predictable."""
        raw = rt.serialize_result([{"a": "b"}], "success")
        assert ", " not in raw
        assert '": "' not in raw


# ── normalize_queries ───────────────────────────────────────────────


class TestNormalizeQueries:
    def test_accepts_one_well_formed_query(self):
        assert rt.normalize_queries([{"query": "alpha beta"}]) == (
            "alpha beta",
        )

    def test_accepts_up_to_max_queries(self):
        value = [{"query": f"term{i} other"} for i in range(rt.MAX_QUERIES)]
        assert len(rt.normalize_queries(value)) == rt.MAX_QUERIES

    def test_strips_surrounding_whitespace(self):
        assert rt.normalize_queries([{"query": "  spaced  "}]) == ("spaced",)

    def test_drops_token_level_duplicates(self):
        """ReMe dedups terms before scoring, so repeats add no evidence."""
        out = rt.normalize_queries(
            [{"query": "alpha beta"}, {"query": "beta alpha"}],
        )
        assert out == ("alpha beta",)

    def test_keeps_distinct_queries_in_order(self):
        out = rt.normalize_queries(
            [{"query": "first topic"}, {"query": "second topic"}],
        )
        assert out == ("first topic", "second topic")

    def test_rejects_a_non_list(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries({"query": "x"})
        assert exc.value.code == "invalid_queries"

    def test_rejects_an_empty_list(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries([])
        assert exc.value.code == "invalid_queries"

    def test_rejects_more_than_max_queries(self):
        value = [{"query": f"t{i}"} for i in range(rt.MAX_QUERIES + 1)]
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries(value)
        assert exc.value.code == "invalid_queries"

    def test_rejects_a_non_dict_item(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries(["just a string"])
        assert exc.value.code == "invalid_query"

    def test_rejects_extra_fields_on_an_item(self):
        """Exactly one `query` key is required - no smuggling extra fields."""
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries([{"query": "x", "extra": "y"}])
        assert exc.value.code == "invalid_query"

    def test_rejects_a_non_string_query(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries([{"query": 42}])
        assert exc.value.code == "invalid_query"

    def test_rejects_a_blank_query(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries([{"query": "   "}])
        assert exc.value.code == "invalid_query"

    def test_rejects_a_query_over_the_char_limit(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries([{"query": "a" * (rt.MAX_QUERY_CHARS + 1)}])
        assert exc.value.code == "invalid_query"

    def test_accepts_a_query_at_the_char_limit(self):
        long_query = "a" * rt.MAX_QUERY_CHARS
        assert rt.normalize_queries([{"query": long_query}]) == (long_query,)

    def test_rejects_a_query_with_no_searchable_tokens(self):
        """Punctuation-only input tokenizes to nothing."""
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.normalize_queries([{"query": "!!! ... ???"}])
        assert exc.value.code == "invalid_query"


# ── message_sources ─────────────────────────────────────────────────


class _Block:
    def __init__(self, block_type, **kwargs):
        # Param renamed off `type` to avoid shadowing the builtin (W0622);
        # all 15 call sites pass it positionally.
        self.type = block_type
        self.__dict__.update(kwargs)


class _Message:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class TestMessageSources:
    def test_text_block_keeps_the_role_prefix(self):
        sources = rt.message_sources(
            _Message("user", [_Block("text", text="hello")]),
        )
        assert len(sources) == 1
        assert sources[0].text == "hello"
        assert sources[0].prefix == "user: "

    def test_skips_empty_text_blocks(self):
        assert (
            rt.message_sources(_Message("user", [_Block("text", text="")]))
            == []
        )

    def test_tool_call_uses_its_input_as_text(self):
        sources = rt.message_sources(
            _Message(
                "assistant",
                [_Block("tool_call", name="search", input="find X")],
            ),
        )
        assert sources[0].text == "find X"
        assert sources[0].prefix == "assistant [tool_call name=search]: "

    def test_tool_result_flattens_its_output(self):
        sources = rt.message_sources(
            _Message(
                "user",
                [_Block("tool_result", name="search", output="line1\nline2")],
            ),
        )
        assert "line1" in sources[0].text
        assert sources[0].prefix == "user [tool_result name=search]: "

    def test_hint_block_is_projected(self):
        sources = rt.message_sources(
            _Message("system", [_Block("hint", hint="be careful")]),
        )
        assert sources[0].text == "be careful"
        assert sources[0].prefix == "system [hint]: "

    def test_recall_tool_own_blocks_are_skipped(self):
        """Recall must not index its own tool traffic (recursion guard)."""
        for name in sorted(rt._RECALL_TOOLS):
            sources = rt.message_sources(
                _Message(
                    "assistant",
                    [_Block("tool_call", name=name, input="nested")],
                ),
            )
            assert sources == [], f"{name} should be skipped"

    def test_recall_tool_result_blocks_are_skipped_too(self):
        sources = rt.message_sources(
            _Message(
                "user",
                [_Block("tool_result", name="recall_context", output="x")],
            ),
        )
        assert sources == []

    def test_unknown_block_types_are_skipped(self):
        sources = rt.message_sources(
            _Message("user", [_Block("image", url="http://x")]),
        )
        assert sources == []

    def test_multiple_blocks_in_order(self):
        sources = rt.message_sources(
            _Message(
                "user",
                [_Block("text", text="one"), _Block("text", text="two")],
            ),
        )
        assert [s.text for s in sources] == ["one", "two"]


# ── context_sources ─────────────────────────────────────────────────


class _State:
    def __init__(self, context):
        self.context = context


class TestContextSources:
    def test_none_state_raises_context_unavailable(self):
        with pytest.raises(rt.RecallRequestError) as exc:
            rt.context_sources(None)
        assert exc.value.code == "context_unavailable"

    def test_excludes_system_messages(self):
        state = _State(
            [
                _Message("system", [_Block("text", text="sys prompt")]),
                _Message("user", [_Block("text", text="real question")]),
            ],
        )
        sources = rt.context_sources(state)
        assert [s.text for s in sources] == ["real question"]

    def test_flattens_all_non_system_messages(self):
        state = _State(
            [
                _Message("user", [_Block("text", text="a")]),
                _Message("assistant", [_Block("text", text="b")]),
            ],
        )
        assert [s.text for s in rt.context_sources(state)] == ["a", "b"]

    def test_empty_context_yields_no_sources(self):
        assert rt.context_sources(_State([])) == ()

    def test_returns_a_tuple(self):
        assert isinstance(rt.context_sources(_State([])), tuple)


# ── search_sources (real ReMe index) ───────────────────────────────


class TestSearchSources:
    async def test_finds_a_matching_passage(self):
        sources = (
            rt.TextSource("the quick brown fox jumps", "user: "),
            rt.TextSource("completely unrelated content", "assistant: "),
        )
        out = json.loads(
            await rt.search_sources(sources, ("quick fox",), 50_000),
        )
        assert out["status"] == "success"
        assert any("quick brown fox" in r["passage"] for r in out["results"])

    async def test_no_match_returns_no_match_status(self):
        sources = (rt.TextSource("alpha beta gamma", "user: "),)
        out = json.loads(
            await rt.search_sources(sources, ("zzzqqqxyz",), 50_000),
        )
        assert out["status"] == "no_match"
        assert out["results"] == []

    async def test_empty_sources_return_no_match(self):
        out = json.loads(await rt.search_sources((), ("anything",), 50_000))
        assert out["status"] == "no_match"

    async def test_prefix_is_attached_to_each_passage(self):
        sources = (rt.TextSource("find this needle", "user: "),)
        out = json.loads(await rt.search_sources(sources, ("needle",), 50_000))
        assert out["results"][0]["passage"].startswith("user: ")

    async def test_dedupes_identical_sources(self):
        """dict.fromkeys() drops exact duplicates (text + attribution)."""
        same = rt.TextSource("duplicate passage here", "user: ")
        out = json.loads(
            await rt.search_sources((same, same), ("duplicate",), 50_000),
        )
        passages = [r["passage"] for r in out["results"]]
        assert len(passages) == len(set(passages))

    async def test_same_text_different_speaker_is_kept(self):
        """Equality includes attribution, so speakers stay distinct."""
        a = rt.TextSource("shared sentence", "user: ")
        b = rt.TextSource("shared sentence", "assistant: ")
        out = json.loads(await rt.search_sources((a, b), ("shared",), 50_000))
        prefixes = {r["passage"].split("shared")[0] for r in out["results"]}
        assert "user: " in prefixes or "assistant: " in prefixes

    async def test_multiple_queries_are_all_served(self):
        sources = (
            rt.TextSource("first topic about apples", "user: "),
            rt.TextSource("second topic about oranges", "assistant: "),
        )
        out = json.loads(
            await rt.search_sources(sources, ("apples", "oranges"), 50_000),
        )
        blob = " ".join(r["passage"] for r in out["results"])
        assert "apples" in blob
        assert "oranges" in blob

    async def test_tiny_budget_raises_result_budget(self):
        """A budget too small for any passage is a model-correctable error."""
        sources = (rt.TextSource("a rather long passage of text", "user: "),)
        with pytest.raises(rt.RecallRequestError) as exc:
            await rt.search_sources(sources, ("passage",), 40)
        assert exc.value.code == "result_budget"


# ── _bounded_passage ───────────────────────────────────────────────


class TestBoundedPassage:
    def test_whole_text_returned_when_it_fits(self):
        source = rt.TextSource("short", "user: ")
        start, end = rt._bounded_passage(
            [],
            source,
            "short",
            rt.make_tokenizer(),
            50_000,
        )
        assert (start, end) == (0, len("short"))

    def test_span_is_trimmed_to_the_budget(self):
        source = rt.TextSource("x" * 5000, "user: ")
        start, end = rt._bounded_passage(
            [],
            source,
            "x",
            rt.make_tokenizer(),
            300,
        )
        assert end - start < 5000
        assert end - start > 0

    def test_window_starts_near_a_match(self):
        text = "padding " * 200 + "needle " + "trailing " * 200
        source = rt.TextSource(text, "user: ")
        start, _end = rt._bounded_passage(
            [],
            source,
            "needle",
            rt.make_tokenizer(),
            400,
        )
        # The match is far into the text, so the window must start near it.
        assert start > 0
        assert text.find("needle") - start <= rt.PASSAGE_CONTEXT_CHARS

    def test_zero_width_span_when_nothing_fits(self):
        source = rt.TextSource("y" * 10_000, "user: ")
        start, end = rt._bounded_passage(
            [],
            source,
            "y",
            rt.make_tokenizer(),
            60,
        )
        assert start == end


# ── make_recall_context_tool / configure_recall_tool ───────────────
#
# ToolChunk.content holds agentscope TextBlock objects, which are pydantic
# models - not dicts - so the payload is read via `.text` (subscripting them
# raises TypeError).


class TestToolFactory:
    def test_returns_a_callable_with_the_public_description(self):
        tool = rt.make_recall_context_tool()
        assert callable(tool)
        assert tool.__doc__ == rt.RECALL_DESCRIPTION

    async def test_rejects_unexpected_kwargs(self, monkeypatch):
        tool = rt.make_recall_context_tool()
        chunk = await tool(queries=[{"query": "x y"}], bogus=1)
        payload = json.loads(chunk.content[0].text)
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "invalid_queries"
        assert chunk.state.name == "ERROR"

    async def test_invalid_queries_surface_as_a_tool_error(self):
        tool = rt.make_recall_context_tool()
        chunk = await tool(queries="not-a-list")
        payload = json.loads(chunk.content[0].text)
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "invalid_queries"

    async def test_unavailable_context_is_reported_not_raised(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(rt, "get_current_agent_state", lambda: None)
        tool = rt.make_recall_context_tool()
        chunk = await tool(queries=[{"query": "alpha beta"}])
        payload = json.loads(chunk.content[0].text)
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "context_unavailable"

    async def test_success_path_returns_passages(self, monkeypatch):
        state = _State(
            [_Message("user", [_Block("text", text="the needle is here")])],
        )
        monkeypatch.setattr(rt, "get_current_agent_state", lambda: state)
        tool = rt.make_recall_context_tool()
        chunk = await tool(queries=[{"query": "needle"}])

        payload = json.loads(chunk.content[0].text)
        assert payload["status"] == "success"
        assert any("needle" in r["passage"] for r in payload["results"])
        assert chunk.state.name == "SUCCESS"
        assert chunk.is_last is True

    async def test_unexpected_exception_becomes_recall_failed(
        self,
        monkeypatch,
    ):
        def explode():
            raise RuntimeError("kaboom")

        monkeypatch.setattr(rt, "get_current_agent_state", explode)
        tool = rt.make_recall_context_tool()
        chunk = await tool(queries=[{"query": "alpha beta"}])

        payload = json.loads(chunk.content[0].text)
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "recall_failed"
        assert chunk.state.name == "ERROR"

    async def test_context_change_between_reads_is_flagged(self, monkeypatch):
        """The tool reads context_sources twice on the SAME state object
        (get_current_agent_state is called once). To exercise the drift guard,
        make context_sources return a different snapshot on each call.
        """
        state = _State([_Message("user", [_Block("text", text="v1")])])
        monkeypatch.setattr(rt, "get_current_agent_state", lambda: state)

        snapshots = iter(
            [
                (rt.TextSource("first read", "user: "),),
                (rt.TextSource("second read", "user: "),),
            ],
        )
        monkeypatch.setattr(rt, "context_sources", lambda _s: next(snapshots))

        tool = rt.make_recall_context_tool()
        chunk = await tool(queries=[{"query": "read"}])

        payload = json.loads(chunk.content[0].text)
        assert payload["status"] == "error"
        assert payload["error"]["code"] == "context_changed"
        assert chunk.state.name == "ERROR"


class TestConfigureRecallTool:
    def test_sets_schema_description_and_read_only(self):
        class _Tool:
            pass

        tool = _Tool()
        returned = rt.configure_recall_tool(tool)

        assert returned is tool
        assert tool.input_schema == rt.RECALL_INPUT_SCHEMA
        assert tool.description == rt.RECALL_DESCRIPTION
        assert tool.is_read_only is True

    def test_schema_is_a_deep_copy(self):
        class _Tool:
            pass

        first = rt.configure_recall_tool(_Tool())
        first.input_schema["properties"]["injected"] = True

        second = rt.configure_recall_tool(_Tool())
        assert "injected" not in second.input_schema
        assert "injected" not in rt.RECALL_INPUT_SCHEMA
