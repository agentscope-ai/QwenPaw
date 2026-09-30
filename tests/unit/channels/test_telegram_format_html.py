# -*- coding: utf-8 -*-
"""Fenced code blocks in the Telegram Markdown-to-HTML converter."""
import pytest

from qwenpaw.app.channels.telegram.format_html import markdown_to_telegram_html


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            "```c++\nint main() { return 0; }\n```",
            '<pre><code class="language-c++">'
            "int main() { return 0; }\n</code></pre>",
            id="info-string-with-symbols",
        ),
        pytest.param(
            "```objective-c\n[obj run];\n```",
            '<pre><code class="language-objective-c">'
            "[obj run];\n</code></pre>",
            id="info-string-with-hyphen",
        ),
        pytest.param(
            "~~~python\n# setup\ndef __init__(self): pass\n~~~",
            '<pre><code class="language-python">'
            "# setup\ndef __init__(self): pass\n</code></pre>",
            id="tilde-fence",
        ),
        pytest.param(
            "````markdown\n```python\nx = 1\n```\n````\nAfter **bold**",
            '<pre><code class="language-markdown">'
            "```python\nx = 1\n```\n</code></pre>\nAfter <b>bold</b>",
            id="longer-fence-around-example",
        ),
    ],
)
def test_fenced_code_is_rendered_as_code(markdown: str, expected: str) -> None:
    assert markdown_to_telegram_html(markdown) == expected


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            "```python\nx = __y__\n```",
            '<pre><code class="language-python">x = __y__\n</code></pre>',
            id="plain-backtick-fence",
        ),
        pytest.param(
            "```\na < b\n```",
            "<pre>a &lt; b\n</pre>",
            id="no-language",
        ),
        pytest.param(
            "```python\nx = 1",
            "```python\nx = 1",
            id="unclosed-fence",
        ),
    ],
)
def test_existing_fence_output_is_unchanged(
    markdown: str,
    expected: str,
) -> None:
    assert markdown_to_telegram_html(markdown) == expected


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            '```a"onmouseover="alert(1)\ncode\n```',
            '<pre><code class="language-a&quot;onmouseover=&quot;alert(1)">'
            "code\n</code></pre>",
            id="info-string-with-quote-is-escaped-in-attribute",
        ),
        pytest.param(
            "```python\r\nx = 1\r\n```",
            '<pre><code class="language-python">x = 1\r\n</code></pre>',
            id="crlf-line-endings",
        ),
        pytest.param(
            "```python\nx\n`````",
            '<pre><code class="language-python">x\n</code></pre>',
            id="longer-closing-run",
        ),
        pytest.param(
            "```python {.highlight}\nx\n```",
            '<pre><code class="language-python">x\n</code></pre>',
            id="info-string-with-attributes",
        ),
        pytest.param(
            # As in CommonMark, an unclosed fence runs until a bare closing
            # run: "```bash" has an info string, so it is code, not a close.
            "```python\nx = 1\nSome prose\n```bash\ny = 2\n```",
            '<pre><code class="language-python">'
            "x = 1\nSome prose\n```bash\ny = 2\n</code></pre>",
            id="fence-with-info-string-does-not-close",
        ),
    ],
)
def test_fence_edge_cases(markdown: str, expected: str) -> None:
    assert markdown_to_telegram_html(markdown) == expected
