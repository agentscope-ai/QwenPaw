# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.utils.setup_utils.

Covers:
- normalize_agent_language
- _resolve_md_lang_dir
- _template_fallback_language_order
- _copy_template_md_files
- _remove_bootstrap_from_workspace
- copy_template_md_files
- copy_workspace_md_files
- copy_builtin_qa_md_files
"""
# pylint: disable=protected-access,unused-argument

from unittest.mock import patch

from qwenpaw.agents.utils.setup_utils import (
    _copy_template_md_files,
    _remove_bootstrap_from_workspace,
    _resolve_md_lang_dir,
    _template_fallback_language_order,
    copy_builtin_qa_md_files,
    copy_template_md_files,
    copy_workspace_md_files,
    normalize_agent_language,
)


# ---------------------------------------------------------------------------
# normalize_agent_language
# ---------------------------------------------------------------------------


class TestNormalizeAgentLanguage:
    """Tests for normalize_agent_language."""

    def test_supported_language(self):
        from qwenpaw.constant import SUPPORTED_AGENT_LANGUAGES

        if "en" in SUPPORTED_AGENT_LANGUAGES:
            assert normalize_agent_language("en") == "en"

    def test_unsupported_language_falls_back(self):
        result = normalize_agent_language("xx")
        assert result == "en"


# ---------------------------------------------------------------------------
# _resolve_md_lang_dir
# ---------------------------------------------------------------------------


class TestResolveMdLangDir:
    """Tests for _resolve_md_lang_dir."""

    def test_existing_dir(self, tmp_path):
        # _resolve_md_lang_dir appends language to agents_root
        # so agents_root / "md_files" / "en" must exist
        agents_root = tmp_path
        md_dir = agents_root / "md_files" / "en"
        md_dir.mkdir(parents=True)
        result = _resolve_md_lang_dir(agents_root, "en")
        assert result == md_dir

    def test_missing_dir_falls_back(self, tmp_path):
        agents_root = tmp_path
        en_dir = agents_root / "md_files" / "en"
        en_dir.mkdir(parents=True)
        result = _resolve_md_lang_dir(agents_root, "fr")
        assert result == en_dir


# ---------------------------------------------------------------------------
# _template_fallback_language_order
# ---------------------------------------------------------------------------


class TestTemplateFallbackLanguageOrder:
    """Tests for _template_fallback_language_order."""

    def test_default_order(self):
        result = _template_fallback_language_order("en")
        assert result[0] == "en"

    def test_chinese_order(self):
        result = _template_fallback_language_order("zh")
        assert result[0] == "zh"
        assert "en" in result

    def test_no_duplicates(self):
        result = _template_fallback_language_order("en")
        assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# _copy_template_md_files
# ---------------------------------------------------------------------------


class TestCopyTemplateMdFilesInternal:
    """Tests for _copy_template_md_files."""

    def test_copies_from_first_lang(self, tmp_path):
        template_root = tmp_path / "template"
        en_dir = template_root / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "AGENTS.md").write_text("agents content")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _copy_template_md_files(
            template_root,
            ["en"],
            workspace,
            only_if_missing=True,
        )
        assert "AGENTS.md" in result
        assert (workspace / "AGENTS.md").exists()

    def test_only_if_missing_skips_existing(self, tmp_path):
        template_root = tmp_path / "template"
        en_dir = template_root / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "AGENTS.md").write_text("new content")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "AGENTS.md").write_text("old content")

        result = _copy_template_md_files(
            template_root,
            ["en"],
            workspace,
            only_if_missing=True,
        )
        assert "AGENTS.md" not in result
        assert (workspace / "AGENTS.md").read_text() == "old content"

    def test_overwrites_when_not_only_if_missing(self, tmp_path):
        template_root = tmp_path / "template"
        en_dir = template_root / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "AGENTS.md").write_text("new content")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "AGENTS.md").write_text("old content")

        result = _copy_template_md_files(
            template_root,
            ["en"],
            workspace,
            only_if_missing=False,
        )
        assert "AGENTS.md" in result
        assert (workspace / "AGENTS.md").read_text() == "new content"

    def test_fallback_to_second_lang(self, tmp_path):
        template_root = tmp_path / "template"
        en_dir = template_root / "en"
        en_dir.mkdir(parents=True)
        (en_dir / "AGENTS.md").write_text("en content")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = _copy_template_md_files(
            template_root,
            ["zh", "en"],
            workspace,
            only_if_missing=True,
        )
        assert "AGENTS.md" in result


# ---------------------------------------------------------------------------
# _remove_bootstrap_from_workspace
# ---------------------------------------------------------------------------


class TestRemoveBootstrapFromWorkspace:
    """Tests for _remove_bootstrap_from_workspace."""

    def test_removes_existing(self, tmp_path):
        bootstrap = tmp_path / "BOOTSTRAP.md"
        bootstrap.write_text("bootstrap content")
        _remove_bootstrap_from_workspace(tmp_path)
        assert not bootstrap.exists()

    def test_no_file_no_error(self, tmp_path):
        _remove_bootstrap_from_workspace(tmp_path)


# ---------------------------------------------------------------------------
# copy_workspace_md_files / copy_builtin_qa_md_files (mocked)
# ---------------------------------------------------------------------------


class TestCopyWorkspaceMdFiles:
    """Tests for copy_workspace_md_files."""

    def test_without_template(self, tmp_path):
        with patch(
            "qwenpaw.agents.utils.setup_utils.copy_md_files",
            return_value=["AGENTS.md"],
        ):
            result = copy_workspace_md_files("en", tmp_path)
            assert "AGENTS.md" in result

    def test_with_template(self, tmp_path):
        with patch(
            "qwenpaw.agents.utils.setup_utils.copy_md_files",
            return_value=["AGENTS.md"],
        ), patch(
            "qwenpaw.agents.utils.setup_utils.copy_template_md_files",
            return_value=["SOUL.md"],
        ):
            result = copy_workspace_md_files(
                "en",
                tmp_path,
                md_template_id="qa",
            )
            assert "AGENTS.md" in result
            assert "SOUL.md" in result


class TestCopyBuiltinQaMdFiles:
    """Tests for copy_builtin_qa_md_files."""

    def test_delegates_to_copy_workspace_md_files(self, tmp_path):
        with patch(
            "qwenpaw.agents.utils.setup_utils.copy_workspace_md_files",
            return_value=["AGENTS.md"],
        ) as mock:
            result = copy_builtin_qa_md_files("en", tmp_path)
            mock.assert_called_once_with(
                "en",
                tmp_path,
                md_template_id="qa",
                only_if_missing=True,
            )
            assert result == ["AGENTS.md"]


class TestCopyTemplateMdFiles:
    """Tests for copy_template_md_files."""

    def test_nonexistent_template_returns_empty(self, tmp_path):
        result = copy_template_md_files(
            "nonexistent_template_xyz",
            "en",
            tmp_path,
        )
        assert not result
