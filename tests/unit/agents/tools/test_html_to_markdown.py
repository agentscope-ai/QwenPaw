# -*- coding: utf-8 -*-
"""Tests for the stdlib HTML -> Markdown converter used by web_fetch."""

from qwenpaw.agents.tools._html_to_markdown import html_to_markdown


def test_drops_non_content_and_images():
    html = (
        "<head><title>T</title><style>.a{}</style></head>"
        "<body><script>x()</script><p>hi <img src='i.png' alt='p'></p>"
        "</body>"
    )
    assert html_to_markdown(html) == "hi"


def test_headings_emphasis_and_links():
    html = (
        "<h2>Title   <em>here</em></h2>"
        "<p>A <b>bold</b> <a href='https://x.com'>link</a>"
        " and <a href='#frag'>anchor</a> &amp; more</p>"
    )
    assert html_to_markdown(html) == (
        "## Title *here*\n\nA **bold** [link](https://x.com) and anchor & more"
    )


def test_lists_nested_and_ordered():
    html = (
        "<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul>"
        "<ol><li>a</li><li>b</li></ol>"
    )
    assert html_to_markdown(html) == "* one\n* two\n  * nested\n\n1. a\n2. b"


def test_pre_preserves_whitespace():
    html = "<p>x</p><pre><code>def f():\n    return 1\n</code></pre>"
    assert html_to_markdown(html) == "x\n\n```\ndef f():\n    return 1\n```"


def test_table_and_blockquote():
    html = (
        "<table><tr><th>A</th><th>B</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
        "<blockquote><p>quoted</p></blockquote>"
    )
    assert html_to_markdown(html) == "| A | B |\n| 1 | 2 |\n\n> quoted"


def test_plain_and_unclosed_input():
    assert html_to_markdown("") == ""
    assert html_to_markdown("plain") == "plain"
    assert html_to_markdown("<p>open <a href='u'>link") == "open [link](u)"


def test_missing_head_end_tag_keeps_body():
    html = "<html><head><title>T</title><meta charset=utf-8><body><p>Hi</p>"
    assert html_to_markdown(html) == "Hi"


def test_button_text_is_kept():
    assert html_to_markdown("<p>Click <button>Submit</button></p>") == (
        "Click Submit"
    )


def test_emphasis_moves_inner_spaces_outside():
    assert html_to_markdown("<p>A<b> bold </b>text</p>") == "A **bold** text"


def test_literal_fence_in_text_keeps_pre_intact():
    html = "<p>use <code>```</code></p><pre>a  b\n\n\nc</pre><p>x    y</p>"
    assert html_to_markdown(html) == (
        "use ```\n\n```\na  b\n\n\nc\n```\n\nx y"
    )


def test_markup_inside_pre_stays_plain():
    html = "<pre><code>a = <b>1</b> <a href='u'>f</a>()</code></pre>"
    assert html_to_markdown(html) == "```\na = 1 f()\n```"


def test_block_content_in_link_is_flattened():
    html = "<a href='https://x'><div><h3>Title</h3><p>desc</p></div></a>"
    assert html_to_markdown(html) == "[Title desc](https://x)"


def test_paragraph_in_list_item_stays_on_marker_line():
    html = "<ul><li><p>one</p></li><li><p>two</p></li></ul>"
    assert html_to_markdown(html) == "* one\n\n* two"


def test_bad_nesting_closes_inner_tags():
    html = "<p>x <a href='u'><b>y</a></b> z</p>"
    assert html_to_markdown(html) == "x [**y**](u) z"


def test_pre_inside_blockquote_is_quoted():
    html = "<blockquote><p>q</p><pre>a\nb</pre></blockquote>"
    assert html_to_markdown(html) == "> q\n>\n> ```\n> a\n> b\n> ```"


def test_empty_list_items_do_not_swallow_following_blocks():
    html = (
        "<ul><li><a href='https://x/a'>"
        "<svg><title>X</title><path d='M0'/></svg></a></li>"
        "<li><img src=x></li></ul><h2>Next</h2><p>body</p>"
    )
    assert html_to_markdown(html) == "## Next\n\nbody"


def test_empty_ordered_item_keeps_numbering():
    html = "<ol><li>a<li><img src=x><li>c</ol>"
    assert html_to_markdown(html) == "1. a\n2. c"


def test_pre_wrapped_in_link_or_emphasis_keeps_code():
    assert html_to_markdown("<a href='u'><pre>x</pre></a>") == "```\nx\n```"
    assert html_to_markdown("<b><pre>y  z</pre></b>") == "```\ny  z\n```"


def test_unclosed_select_does_not_hide_rest_of_body():
    html = "<body><select><option>a<p>after</p>"
    assert html_to_markdown(html) == "a\n\nafter"


def test_script_like_links_are_case_insensitive():
    html = "<a href='JavaScript:x'>j</a> <a href='DATA:text/html,x'>d</a>"
    assert html_to_markdown(html) == "j d"


def test_consecutive_line_breaks_add_up():
    assert html_to_markdown("<p>a<br>b<br><br>c</p>") == "a\nb\n\nc"


def test_template_content_is_kept_not_swallowed():
    assert html_to_markdown("<template><p>a</p><p>x</p>") == "a\n\nx"


def test_select_options_are_separated():
    html = "<p>Lang: <select><option>English</option><option>中文</option>"
    assert html_to_markdown(html) == "Lang:\nEnglish\n中文"


def test_inline_code_with_backtick_and_adjacent_emphasis():
    assert html_to_markdown("<code>a`b</code>") == "`` a`b ``"
    assert html_to_markdown("c<i>d</i>") == "c*d*"


def test_link_scheme_check_ignores_leading_whitespace():
    assert html_to_markdown("<a href=' javascript:x'>k</a>") == "k"


def test_link_destination_escapes_parens_and_spaces():
    html = "<a href='https://e.com/a)b'>r</a> <a href='/x y(1)'>s</a>"
    assert html_to_markdown(html) == (
        "[r](https://e.com/a\\)b) [s](/x%20y\\(1\\))"
    )


def test_pre_fence_is_longer_than_backtick_runs_in_code():
    html = "<p>Ex:</p><pre>```python\nx = 1\n```\nprint(x)</pre><p>End.</p>"
    assert html_to_markdown(html) == (
        "Ex:\n\n````\n```python\nx = 1\n```\nprint(x)\n````\n\nEnd."
    )


def test_paragraphs_in_table_cells_stay_on_the_row():
    html = (
        "<table><tr><th>A</th><th>B</th></tr>"
        "<tr><td><p>a1</p></td><td><p>b1</p><p>b2</p></td></tr></table>"
        "<p>after</p>"
    )
    assert html_to_markdown(html) == "| A | B |\n| a1 | b1 b2 |\n\nafter"


def test_ordered_list_honors_start_attribute():
    assert html_to_markdown("<ol start='5'><li>a</li><li>b</li></ol>") == (
        "5. a\n6. b"
    )
    assert html_to_markdown("<ol start='x'><li>a</li></ol>") == "1. a"


def test_omitted_cell_end_tags_keep_rows_and_following_blocks():
    html = "<table><tr><td>A</tr></table><h2>After</h2><p>body</p>"
    assert html_to_markdown(html) == "| A |\n\n## After\n\nbody"
    html = "<table><tr><th>H<td>A<tr><td>B</table><p>after</p>"
    assert html_to_markdown(html) == "| H | A |\n| B |\n\nafter"
