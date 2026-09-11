# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for skills hub helpers (qwenpaw.agents.skill_system.hub).

Coverage-driven backfill (batch 2, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the pure parsing /
normalisation / URL-spec extraction layer of the hub module, which
previously sat at ~14% coverage. Network-dependent paths are exercised
separately (integration layer).
"""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from qwenpaw.agents.skill_system import hub
from qwenpaw.exceptions import SkillsError

# ---------------------------------------------------------------------------
# Env-driven config readers
# ---------------------------------------------------------------------------


class TestEnvConfigReaders:
    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [("", 300.0), ("60", 60.0), ("-5", 0.0), ("junk", 300.0)],
    )
    def test_github_cache_ttl(self, monkeypatch, env_value, expected):
        monkeypatch.setenv("QWENPAW_GITHUB_CACHE_TTL", env_value)
        assert hub._github_cache_ttl() == expected

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [("", 30.0), ("5", 5.0), ("1", 3.0), ("junk", 30.0)],
    )
    def test_http_timeout(self, monkeypatch, env_value, expected):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", env_value)
        assert hub._hub_http_timeout() == expected

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [("", 3), ("5", 5), ("-2", 0), ("junk", 3)],
    )
    def test_http_retries(self, monkeypatch, env_value, expected):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", env_value)
        assert hub._hub_http_retries() == expected

    def test_backoff_base_and_cap_defaults(self, monkeypatch):
        monkeypatch.delenv(
            "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE",
            raising=False,
        )
        monkeypatch.delenv(
            "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP",
            raising=False,
        )
        assert hub._hub_http_backoff_base() == 0.8
        assert hub._hub_http_backoff_cap() == 6.0

    def test_backoff_base_junk_falls_back(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "junk")
        assert hub._hub_http_backoff_base() == 0.8

    def test_backoff_cap_junk_falls_back(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "junk")
        assert hub._hub_http_backoff_cap() == 6.0

    def test_backoff_seconds_exponential_then_capped(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "1")
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "4")
        assert hub._compute_backoff_seconds(0) == 1.0
        assert hub._compute_backoff_seconds(1) == 1.0
        assert hub._compute_backoff_seconds(2) == 2.0
        assert hub._compute_backoff_seconds(3) == 4.0
        assert hub._compute_backoff_seconds(9) == 4.0


# ---------------------------------------------------------------------------
# URL builders / joining
# ---------------------------------------------------------------------------


class TestUrlBuilders:
    def test_hub_base_url_default(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_BASE_URL", raising=False)
        assert hub._hub_base_url() == "https://clawhub.ai"

    def test_hub_paths_defaults(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_SEARCH_PATH", raising=False)
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_VERSION_PATH", raising=False)
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_DETAIL_PATH", raising=False)
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_FILE_PATH", raising=False)
        assert hub._hub_search_path() == "/api/v1/search"
        assert "{slug}" in hub._hub_version_path()
        assert "{slug}" in hub._hub_detail_path()
        assert "{slug}" in hub._hub_file_path()

    @pytest.mark.parametrize(
        ("base", "path", "expected"),
        [
            ("https://h.com", "/api", "https://h.com/api"),
            ("https://h.com/", "api", "https://h.com/api"),
            ("https://h.com/", "/api", "https://h.com/api"),
        ],
    )
    def test_join_url(self, base, path, expected):
        assert hub._join_url(base, path) == expected


# ---------------------------------------------------------------------------
# Cancellation hooks
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_no_checker_is_noop(self):
        hub._ensure_not_cancelled()

    def test_checker_false_continues(self):
        token = hub._cancel_checker_ctx.set(lambda: False)
        try:
            hub._ensure_not_cancelled()
        finally:
            hub._cancel_checker_ctx.reset(token)

    def test_checker_true_raises(self):
        token = hub._cancel_checker_ctx.set(lambda: True)
        try:
            with pytest.raises(hub.SkillImportCancelled):
                hub._ensure_not_cancelled()
        finally:
            hub._cancel_checker_ctx.reset(token)

    def test_checker_error_is_swallowed(self):
        def broken():
            raise RuntimeError("checker exploded")

        token = hub._cancel_checker_ctx.set(broken)
        try:
            hub._ensure_not_cancelled()
        finally:
            hub._cancel_checker_ctx.reset(token)


# ---------------------------------------------------------------------------
# Search result normalisation
# ---------------------------------------------------------------------------


class TestNormSearchItems:
    def test_list_passthrough_drops_non_dicts(self):
        assert hub._norm_search_items([{"a": 1}, "x", 5]) == [{"a": 1}]

    @pytest.mark.parametrize("key", ["items", "skills", "results", "data"])
    def test_dict_container_key(self, key):
        data = {key: [{"slug": "s"}, "junk"]}
        assert hub._norm_search_items(data) == [{"slug": "s"}]

    def test_single_skill_dict(self):
        assert hub._norm_search_items({"name": "n", "slug": "s"}) == [
            {"name": "n", "slug": "s"},
        ]

    def test_unknown_shape(self):
        assert hub._norm_search_items(None) == []
        assert hub._norm_search_items("x") == []
        assert hub._norm_search_items({"weird": 1}) == []


# ---------------------------------------------------------------------------
# Bundle tree helpers
# ---------------------------------------------------------------------------


class TestSafePathParts:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("a/b.txt", ["a", "b.txt"]),
            ("a//b", ["a", "b"]),
            ("", None),
            ("/abs", None),
            ("a/../b", None),
            ("a/./b", None),
            ("//", None),
        ],
    )
    def test_variants(self, path, expected):
        assert hub._safe_path_parts(path) == expected


class TestFilesToTree:
    def test_references_and_scripts_split(self):
        files = {
            "references/doc.md": "docs",
            "scripts/run.py": "print(1)",
            "SKILL.md": "---\nname: x\n---\n",
            "other/extra.txt": "e",
        }
        references, scripts = hub._files_to_tree(files)
        assert references == {"doc.md": "docs"}
        assert scripts == {"run.py": "print(1)"}

    def test_nested_directories(self):
        references, scripts = hub._files_to_tree(
            {"references/a/b.md": "deep"},
        )
        assert references == {"a": {"b.md": "deep"}}

    def test_invalid_entries_skipped(self):
        references, scripts = hub._files_to_tree(
            {
                "references": "bare dir",
                "/abs.md": "x",
                "scripts/../x.py": "x",
                5: "not str",
            },
        )
        assert references == {}
        assert scripts == {}


class TestSanitizeTree:
    def test_drops_dangerous_keys(self):
        tree = {
            "ok.txt": "x",
            ".": "x",
            "..": "x",
            "a/b": "x",
            "c\\d": "x",
            5: "x",
            "nested": {"good.md": "y"},
            "junk": ["not", "str"],
        }
        assert hub._sanitize_tree(tree) == {
            "ok.txt": "x",
            "nested": {"good.md": "y"},
        }

    def test_non_dict_returns_empty(self):
        assert hub._sanitize_tree(["a"]) == {}
        assert hub._sanitize_tree(None) == {}


class TestBundleHasContent:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"content": " x "}, True),
            ({"skill_md": "x"}, True),
            ({"skillMd": "x"}, True),
            ({"files": {"SKILL.md": "x"}}, True),
            ({"content": "   "}, False),
            ({"files": {}}, False),
            ({}, False),
            ("not dict", False),
        ],
    )
    def test_variants(self, payload, expected):
        assert hub._bundle_has_content(payload) is expected


class TestExtractVersionHint:
    def test_requested_version_wins(self):
        assert hub._extract_version_hint({}, "1.2.3") == "1.2.3"

    def test_latest_version_field(self):
        detail = {"latestVersion": {"version": "2.0.0"}}
        assert hub._extract_version_hint(detail, "") == "2.0.0"

    def test_skill_tags_latest(self):
        detail = {"skill": {"tags": {"latest": "3.1"}}}
        assert hub._extract_version_hint(detail, "") == "3.1"

    def test_no_hint(self):
        assert hub._extract_version_hint({}, "") == ""
        assert hub._extract_version_hint({"latestVersion": "x"}, "") == ""


# ---------------------------------------------------------------------------
# Bundle normalisation
# ---------------------------------------------------------------------------


class TestNormalizeBundle:
    SKILL_MD = "---\nname: parsed-name\n---\n# body\n"

    def test_simple_bundle(self):
        name, content, refs, scripts, extra = hub._normalize_bundle(
            {
                "name": "explicit",
                "content": self.SKILL_MD,
                "references": {"a.md": "r"},
                "scripts": {"s.py": "x"},
            },
        )
        assert name == "explicit"
        assert content == self.SKILL_MD
        assert refs == {"a.md": "r"}
        assert scripts == {"s.py": "x"}
        assert extra == {}

    def test_wrapper_skill_key_unwrapped(self):
        name, content, *_ = hub._normalize_bundle(
            {"skill": {"name": "inner", "content": self.SKILL_MD}},
        )
        assert name == "inner"
        assert content == self.SKILL_MD

    def test_wrapper_with_content_not_unwrapped(self):
        name, _, _, _, _ = hub._normalize_bundle(
            {
                "skill": {"name": "ignored"},
                "name": "outer",
                "content": self.SKILL_MD,
            },
        )
        assert name == "outer"

    def test_name_falls_back_to_frontmatter(self):
        name, *_ = hub._normalize_bundle({"content": self.SKILL_MD})
        assert name == "parsed-name"

    def test_files_mapping_fallback(self):
        payload = {"files": {"SKILL.md": self.SKILL_MD, "extra.txt": "e"}}
        name, content, refs, scripts, extra = hub._normalize_bundle(payload)
        assert name == "parsed-name"
        assert content == self.SKILL_MD
        assert extra == {"extra.txt": "e"}

    def test_files_references_scripts_fallback(self):
        payload = {
            "content": self.SKILL_MD,
            "name": "n",
            "files": {
                "references/r.md": "r",
                "scripts/s.py": "s",
                "SKILL.md": "ignored-dup",
            },
        }
        _, _, refs, scripts, _ = hub._normalize_bundle(payload)
        assert refs == {"r.md": "r"}
        assert scripts == {"s.py": "s"}

    def test_explicit_references_not_overridden_by_files(self):
        payload = {
            "content": self.SKILL_MD,
            "name": "n",
            "references": {"keep.md": "kept"},
            "files": {"references/other.md": "dropped"},
        }
        _, _, refs, _, _ = hub._normalize_bundle(payload)
        assert refs == {"keep.md": "kept"}

    def test_non_object_raises(self):
        with pytest.raises(SkillsError, match="not a valid JSON object"):
            hub._normalize_bundle(["not", "dict"])

    def test_missing_content_raises(self):
        with pytest.raises(SkillsError, match="missing SKILL.md"):
            hub._normalize_bundle({"name": "x"})

    def test_missing_name_raises(self):
        with pytest.raises(SkillsError, match="missing skill name"):
            hub._normalize_bundle({"content": "# no frontmatter"})

    def test_bad_frontmatter_name_falls_back_to_missing(self):
        with pytest.raises(SkillsError, match="missing skill name"):
            hub._normalize_bundle({"content": "---\nname: [unclosed\n---\n"})


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------


class TestNameHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("hello world!", "hello-world"),
            ("--x--", "x"),
            ("!!!", "imported-skill"),
            ("keep_1-2", "keep_1-2"),
        ],
    )
    def test_safe_fallback_name(self, raw, expected):
        assert hub._safe_fallback_name(raw) == expected

    def test_normalize_skill_key(self):
        assert hub._normalize_skill_key("Hello World!") == "hello-world"
        assert hub._normalize_skill_key("--") == ""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("plain", "plain"),
            ("Excel / XLSX", "excel-xlsx"),
            ("win\\sep", "win-sep"),
            ("", "imported-skill"),
            ("///", "imported-skill"),
        ],
    )
    def test_sanitize_skill_dir_name(self, name, expected):
        assert hub._sanitize_skill_dir_name(name) == expected

    def test_sanitize_non_string(self):
        assert hub._sanitize_skill_dir_name(None) == "imported-skill"


class TestIsHttpUrl:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("https://example.com/x", True),
            ("http://example.com", True),
            (" https://example.com ", True),
            ("ftp://example.com", False),
            ("example.com", False),
            ("https://", False),
            ("", False),
        ],
    )
    def test_variants(self, text, expected):
        assert hub._is_http_url(text) is expected


# ---------------------------------------------------------------------------
# Binary / error payload helpers
# ---------------------------------------------------------------------------


class TestProbablyTextBlob:
    def test_empty_is_text(self):
        assert hub._is_probably_text_blob(b"") is True

    def test_nul_is_binary(self):
        assert hub._is_probably_text_blob(b"a\x00b") is False

    def test_plain_text(self):
        assert hub._is_probably_text_blob("héllo wörld".encode()) is True

    def test_mostly_binary(self):
        payload = bytes(range(32)) * 4
        assert hub._is_probably_text_blob(payload) is False


class TestExtractErrorMessageFromPayload:
    def test_empty(self):
        assert hub._extract_error_message_from_payload(b"") == ""

    def test_binary_returns_empty(self):
        assert hub._extract_error_message_from_payload(b"\x00\x01") == ""

    def test_plain_text(self):
        assert (
            hub._extract_error_message_from_payload(b"boom happened")
            == "boom happened"
        )

    def test_json_error_field(self):
        payload = json.dumps({"error": "not found"}).encode()
        assert hub._extract_error_message_from_payload(payload) == "not found"

    def test_json_message_field(self):
        payload = json.dumps({"message": "quota"}).encode()
        assert hub._extract_error_message_from_payload(payload) == "quota"

    def test_json_without_message_fields(self):
        payload = json.dumps({"other": 1}).encode()
        assert (
            hub._extract_error_message_from_payload(payload) == '{"other": 1}'
        )

    def test_whitespace_only(self):
        assert hub._extract_error_message_from_payload(b"   ") == ""


class TestFormatHttpErrorBody:
    def test_json_body_extracted(self):
        response = httpx.Response(
            404,
            content=json.dumps({"error": "gone"}).encode(),
            request=httpx.Request("GET", "https://x.test/y"),
        )
        error = httpx.HTTPStatusError(
            "bad",
            request=response.request,
            response=response,
        )
        assert hub._format_http_error_body(error) == "gone"

    def test_empty_body_falls_back_to_str(self):
        response = httpx.Response(
            500,
            content=b"",
            request=httpx.Request("GET", "https://x.test/y"),
        )
        error = httpx.HTTPStatusError(
            "bad",
            request=response.request,
            response=response,
        )
        assert hub._format_http_error_body(error) == str(error)


# ---------------------------------------------------------------------------
# Hub URL spec extractors
# ---------------------------------------------------------------------------


class TestExtractClawhubSlug:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://clawhub.ai/owner/skill", "skill"),
            ("https://www.clawhub.ai/skill", "skill"),
            ("https://clawhub.ai/", ""),
            ("https://other.com/skill", ""),
        ],
    )
    def test_variants(self, url, expected):
        assert hub._extract_clawhub_slug_from_url(url) == expected

    def test_resolve_clawhub_slug(self):
        assert hub._resolve_clawhub_slug("https://clawhub.ai/a/b") == "b"
        assert hub._resolve_clawhub_slug("https://other.com/a/b") == ""


class TestExtractSkillsShSpec:
    def test_valid(self):
        assert hub._extract_skills_sh_spec(
            "https://skills.sh/owner/repo/skill",
        ) == ("owner", "repo", "skill")

    def test_www(self):
        assert hub._extract_skills_sh_spec(
            "https://www.skills.sh/o/r/s",
        ) == ("o", "r", "s")

    @pytest.mark.parametrize(
        "url",
        [
            "https://skills.sh/owner/repo",
            "https://other.com/o/r/s",
            "https://skills.sh/",
        ],
    )
    def test_invalid(self, url):
        assert hub._extract_skills_sh_spec(url) is None


class TestExtractSkillsmpSlug:
    def test_valid(self):
        assert (
            hub._extract_skillsmp_slug("https://skillsmp.com/skills/abc")
            == "abc"
        )

    def test_trailing_garbage_ok(self):
        assert (
            hub._extract_skillsmp_slug("https://skillsmp.com/skills/abc/x")
            == "abc"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://skillsmp.com/other/abc",
            "https://skillsmp.com/skills",
            "https://other.com/skills/abc",
        ],
    )
    def test_invalid(self, url):
        assert hub._extract_skillsmp_slug(url) == ""


class TestExtractLobehubIdentifier:
    def test_main_site(self):
        assert (
            hub._extract_lobehub_identifier("https://lobehub.com/skills/abc")
            == "abc"
        )

    def test_market_download(self):
        assert (
            hub._extract_lobehub_identifier(
                "https://market.lobehub.com/api/v1/skills/abc/download",
            )
            == "abc"
        )

    def test_url_encoded_segment(self):
        assert (
            hub._extract_lobehub_identifier(
                "https://lobehub.com/skills/my%20skill",
            )
            == "my skill"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://lobehub.com/other/abc",
            "https://lobehub.com/skills",
            "https://market.lobehub.com/api/v1/skills/abc",
            "https://other.com/skills/abc",
        ],
    )
    def test_invalid(self, url):
        assert hub._extract_lobehub_identifier(url) == ""


class TestExtractModelscopeSpec:
    def test_basic(self):
        assert hub._extract_modelscope_skill_spec(
            "https://modelscope.cn/skills/@owner/name",
        ) == ("@owner", "name", "")

    def test_archive_version(self):
        assert hub._extract_modelscope_skill_spec(
            "https://modelscope.cn/skills/o/n/archive/zip/1.0.zip",
        ) == ("o", "n", "1.0")

    @pytest.mark.parametrize(
        "url",
        [
            "https://modelscope.cn/other/o/n",
            "https://modelscope.cn/skills/onlyowner",
            "https://other.com/skills/o/n",
        ],
    )
    def test_invalid(self, url):
        assert hub._extract_modelscope_skill_spec(url) is None


class TestExtractQwenpawSpec:
    def test_uuid_detail_page(self):
        url = (
            "https://platform.agentscope.io/skills/"
            "12345678-1234-1234-1234-123456789abc"
        )
        assert hub._extract_qwenpaw_skill_spec(url) == (
            "",
            "12345678-1234-1234-1234-123456789abc",
            "",
        )

    def test_archive_url(self):
        url = (
            "https://platform.agentscope.io/"
            "skills/@team/skill/archive/zip/2.0.zip"
        )
        assert hub._extract_qwenpaw_skill_spec(url) == (
            "@team",
            "skill",
            "2.0",
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://platform.agentscope.io/other/x",
            "https://platform.agentscope.io/skills",
            "https://platform.agentscope.io/skills/owner",
            "https://other.com/skills/o/n",
        ],
    )
    def test_invalid(self, url):
        assert hub._extract_qwenpaw_skill_spec(url) is None


class TestExtractAliyunSpec:
    def test_valid(self):
        assert (
            hub._extract_aliyun_skill_spec(
                "https://api.aliyun.com/agentexplorer/skills/skill-123",
            )
            == "skill-123"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.aliyun.com/agentexplorer/skills",
            "https://api.aliyun.com/other/skills/x",
            "https://other.com/agentexplorer/skills/x",
        ],
    )
    def test_invalid(self, url):
        assert hub._extract_aliyun_skill_spec(url) is None


class TestExtractGithubSpec:
    def test_repo_only(self):
        assert hub._extract_github_spec("https://github.com/o/r") == (
            "o",
            "r",
            "",
            "",
        )

    def test_tree_branch_and_path(self):
        assert hub._extract_github_spec(
            "https://github.com/o/r/tree/main/skills/x",
        ) == ("o", "r", "main", "skills/x")

    def test_blob_branch(self):
        assert hub._extract_github_spec(
            "https://github.com/o/r/blob/dev/a.md",
        ) == ("o", "r", "dev", "a.md")

    def test_extra_segments_as_path_hint(self):
        assert hub._extract_github_spec("https://github.com/o/r/issues") == (
            "o",
            "r",
            "",
            "issues",
        )

    def test_www(self):
        assert hub._extract_github_spec("https://www.github.com/o/r") == (
            "o",
            "r",
            "",
            "",
        )

    @pytest.mark.parametrize(
        "url",
        ["https://github.com/onlyowner", "https://other.com/o/r"],
    )
    def test_invalid(self, url):
        assert hub._extract_github_spec(url) is None


class TestGithubUrlHelpers:
    def test_api_url(self):
        assert (
            hub._github_api_url("o", "r", "contents/skill")
            == "https://api.github.com/repos/o/r/contents/skill"
        )
        assert (
            hub._github_api_url("o", "r", "")
            == "https://api.github.com/repos/o/r"
        )

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("a b/c", "a%20b/c"),
            ("/x/", "x"),
            ("", ""),
        ],
    )
    def test_encode_path(self, path, expected):
        assert hub._github_encode_path(path) == expected


class TestRepoPathHelpers:
    def test_join_repo_path(self):
        assert hub._join_repo_path("", "leaf") == "leaf"
        assert hub._join_repo_path("root/", "/leaf") == "root/leaf"

    def test_relative_from_root(self):
        assert hub._relative_from_root("root/a/b", "root") == "a/b"
        assert hub._relative_from_root("other/a", "root") == "other/a"
        assert hub._relative_from_root("/x", "") == "x"


# ---------------------------------------------------------------------------
# LobeHub zip → bundle conversion
# ---------------------------------------------------------------------------


def _make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestLobehubHelpers:
    def test_download_url(self):
        assert (
            hub._lobehub_download_url("abc")
            == "https://market.lobehub.com/api/v1/skills/abc/download"
        )

    @pytest.mark.parametrize(
        ("parts", "expected"),
        [
            (["SKILL.md"], True),
            (["references", "a.md"], True),
            (["scripts", "run.py"], True),
            (["top.txt"], True),
            (["SKILL.md", "extra"], False),
            (["nested", "deep.txt"], False),
            ([], False),
        ],
    )
    def test_should_keep_file(self, parts, expected):
        assert hub._should_keep_lobehub_file(parts) is expected


class TestLobehubZipToBundle:
    def test_happy_path(self):
        payload = _make_zip(
            {
                "SKILL.md": "---\nname: zip-skill\n---\n# body",
                "references/doc.md": "docs",
                "extra.txt": "x",
            },
        )
        bundle = hub._lobehub_zip_to_bundle("fallback", payload)
        assert bundle["name"] == "zip-skill"
        assert bundle["files"]["SKILL.md"].startswith("---")
        assert bundle["files"]["references/doc.md"] == "docs"
        assert bundle["files"]["extra.txt"] == "x"

    def test_missing_frontmatter_name_uses_identifier(self):
        payload = _make_zip({"SKILL.md": "# no frontmatter"})
        bundle = hub._lobehub_zip_to_bundle("fallback-id", payload)
        assert bundle["name"] == "fallback-id"

    def test_dangerous_entries_dropped(self):
        payload = _make_zip(
            {
                "SKILL.md": "---\nname: s\n---\n",
                "/abs.md": "x",
                "a/../b.md": "x",
                "dir/": "",
            },
        )
        bundle = hub._lobehub_zip_to_bundle("id", payload)
        assert set(bundle["files"]) == {"SKILL.md"}

    def test_binary_entries_skipped(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: s\n---\n")
            zf.writestr("blob.bin", b"\x00\x01\x02")
        bundle = hub._lobehub_zip_to_bundle("id", buf.getvalue())
        assert "blob.bin" not in bundle["files"]

    def test_missing_skill_md_raises(self):
        payload = _make_zip({"only.txt": "x"})
        with pytest.raises(SkillsError, match="missing SKILL.md"):
            hub._lobehub_zip_to_bundle("id", payload)

    def test_bad_zip_with_message(self):
        with pytest.raises(SkillsError, match="download failed"):
            hub._lobehub_zip_to_bundle("id", b"plain error text")

    def test_bad_zip_without_message(self):
        with pytest.raises(SkillsError, match="valid zip"):
            hub._lobehub_zip_to_bundle("id", b"\x00\x01\x02binary")


# ---------------------------------------------------------------------------
# GitHub response cache (pure state helpers)
# ---------------------------------------------------------------------------


class TestGithubCacheHelpers:
    def setup_method(self):
        hub._github_cache.clear()

    def test_set_get_roundtrip(self):
        hub._github_cache_set("k", "v")
        assert hub._github_cache_get("k") == "v"

    def test_cached_miss_sentinel_when_absent(self):
        assert hub._github_cached("missing") is hub._GITHUB_CACHE_MISS

    def test_cache_get_expired_returns_none(self, monkeypatch):
        hub._github_cache["stale"] = (0.0, "old")
        # monotonic clock is far past the fake timestamp → entry expired.
        assert hub._github_cache_get("stale") is None
        assert "stale" not in hub._github_cache

    def test_prune_evicts_expired_entries(self, monkeypatch):
        hub._github_cache["stale"] = (0.0, "old")
        hub._github_cache["fresh"] = (1e12, "new")
        hub._github_cache_prune(now=1e12)
        assert "stale" not in hub._github_cache
        assert "fresh" in hub._github_cache

    def test_prune_caps_max_entries(self, monkeypatch):
        monkeypatch.setattr(hub, "_GITHUB_CACHE_MAX_ENTRIES", 3)
        for i in range(5):
            hub._github_cache[f"k{i}"] = (1e12 + i, i)
        hub._github_cache_prune(now=0.0)
        assert len(hub._github_cache) <= 3
