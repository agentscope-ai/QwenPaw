# -*- coding: utf-8 -*-
"""Tests for web page content conversion."""

from qwenpaw.agents.tools.web_search import _html_to_text


def test_html_to_text_keeps_page_content_without_metadata_or_images() -> None:
    html = """
    <html>
      <head>
        <title>Example page</title>
        <style>.hidden { display: none; }</style>
      </head>
      <body>
        <h1>Heading</h1>
        <p>Read <a href="https://example.com/source">source</a>.</p>
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
    assert "[source](https://example.com/source)" in text
    assert "- one\n- two" in text
    assert '```\nprint("hello")\n```' in text
    assert "ignored.png" not in text
    assert "ignored image" not in text
    assert "ignored_script" not in text
    assert "display: none" not in text


def test_html_to_text_preserves_unwrapped_paragraph_and_title_only() -> None:
    paragraph = " ".join(f"word{index}" for index in range(50))

    assert _html_to_text(f"<p>{paragraph}</p>") == paragraph
    assert _html_to_text("<title>Example page</title>") == "# Example page"
