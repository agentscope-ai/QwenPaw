# -*- coding: utf-8 -*-
"""Tests for web page content conversion."""

import importlib

import pytest

from agentscope.message import ToolResultState

from qwenpaw.agents.tools.web_search import _html_to_text

web_search_module = importlib.import_module(
    "qwenpaw.agents.tools.web_search",
)


def test_html_to_text_preserves_readable_markdown() -> None:
    html = """
    <html>
      <head>
        <title>Example page</title>
        <style>.hidden { display: none; }</style>
      </head>
      <body>
        <h1>Heading</h1>
        <p>Hello <a href="https://example.com">site</a>.</p>
        <img src="ignored.png" alt="ignored image">
        <ul><li>one</li><li>two</li></ul>
        <pre><code>print("hello")</code></pre>
        <script>ignored_script()</script>
      </body>
    </html>
    """

    text = _html_to_text(html)

    assert text.startswith("# Example page\n\n# Heading")
    assert text.count("Example page") == 1
    assert "[site](https://example.com)" in text
    assert "- one\n- two" in text
    assert '```\nprint("hello")\n```' in text
    assert "ignored.png" not in text
    assert "ignored image" not in text
    assert "ignored_script" not in text
    assert "display: none" not in text


def test_html_to_text_does_not_wrap_long_paragraphs() -> None:
    paragraph = " ".join(f"word{index}" for index in range(50))

    text = _html_to_text(f"<p>{paragraph}</p>")

    assert text == paragraph


def test_html_to_text_handles_title_only() -> None:
    assert _html_to_text("<title>Example page</title>") == "# Example page"


@pytest.mark.asyncio
async def test_web_fetch_returns_converted_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_html(url: str) -> str:
        assert url == "https://example.com/page"
        return """
        <html>
          <head><title>Fetched page</title></head>
          <body>
            <p>Read <a href="https://example.com/source">source</a>.</p>
          </body>
        </html>
        """

    monkeypatch.setattr(
        web_search_module,
        "_fetch_html",
        fake_fetch_html,
    )

    result = await web_search_module.web_fetch(
        "https://example.com/page",
    )

    assert result.state == ToolResultState.SUCCESS
    assert result.is_last is True
    assert len(result.content) == 1
    assert result.content[0].text == (
        "# Fetched page\n\n" "Read [source](https://example.com/source)."
    )
