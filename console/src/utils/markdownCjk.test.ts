import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";

import { normalizeCjkEmphasis } from "./markdownCjk";
import { lexWithRenderer } from "./markdownRendererTokens";

describe("normalizeCjkEmphasis", () => {
  it("repairs all supported emphasis delimiters", () => {
    expect(normalizeCjkEmphasis("**粗体。**后文")).toBe("**粗体**。后文");
    expect(normalizeCjkEmphasis("__粗体！__后文")).toBe("__粗体__！后文");
    expect(normalizeCjkEmphasis("*斜体；*後文")).toBe("*斜体*；後文");
    expect(normalizeCjkEmphasis("_斜体：_かな")).toBe("_斜体_：かな");
  });

  it("repairs combined three-character delimiters", () => {
    expect(normalizeCjkEmphasis("***内容。***后文")).toBe("***内容***。后文");
    expect(normalizeCjkEmphasis("___内容。___后文")).toBe("___内容___。后文");
  });

  it("moves every approved punctuation mark", () => {
    for (const mark of ["。", "！", "？", "；", "：", "，", "、", "…"]) {
      expect(normalizeCjkEmphasis(`**内容${mark}**后`)).toBe(
        `**内容**${mark}后`,
      );
    }
  });

  it("moves trailing full-width closers", () => {
    for (const closer of [
      "”",
      "’",
      "」",
      "』",
      "】",
      "》",
      "〉",
      "）",
      "〕",
      "］",
    ]) {
      expect(normalizeCjkEmphasis(`**内容。${closer}**後`)).toBe(
        `**内容**。${closer}後`,
      );
    }
    expect(normalizeCjkEmphasis("**内容！？…”）**后")).toBe(
      "**内容**！？…”）后",
    );
  });

  it("recognizes Han, Kana, Hangul and supplementary Han followers", () => {
    for (const follower of ["后", "あ", "ア", "한", "𠀀"]) {
      expect(normalizeCjkEmphasis(`**内容。**${follower}`)).toBe(
        `**内容**。${follower}`,
      );
    }
  });

  it("handles multiple, adjacent and nested emphasis", () => {
    expect(normalizeCjkEmphasis("**甲。**乙 __丙！__丁 *戊？*己")).toBe(
      "**甲**。乙 __丙__！丁 *戊*？己",
    );
    expect(normalizeCjkEmphasis("**外层 *内层。*后续**")).toBe(
      "**外层 *内层*。后续**",
    );
  });

  it("does not widen the punctuation or follower scope", () => {
    const unchanged = [
      "**内容.**后",
      "**内容。**latin",
      "**内容。** 后",
      "**内容」**后",
      "plain 中文。**后",
      "**已经规范**。后",
    ];
    for (const source of unchanged) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("preserves fenced, inline and indented code", () => {
    const source = [
      "outside **正文。**后",
      "```markdown",
      "**代码。**后",
      "```",
      "~~~",
      "__代码！__後",
      "~~~",
      "inline `**代码。**后` end",
      // The blank line is what makes the next two lines indented *code*.
      // Without it they continue the paragraph above and CommonMark renders
      // them as ordinary body text, so the repair is supposed to touch them.
      "",
      "    *缩进代码；*後",
      "\t_缩进代码：_かな",
    ].join("\n");
    const expected = source.replace("**正文。**后", "**正文**。后");
    expect(normalizeCjkEmphasis(source)).toBe(expected);
  });

  it("preserves unclosed fenced and inline code", () => {
    const unclosedFence = "before\n```md\n**代码。**后\n";
    const unclosedInline = "before `code **示例。**后\nand more __示例！__後";
    expect(normalizeCjkEmphasis(unclosedFence)).toBe(unclosedFence);
    expect(normalizeCjkEmphasis(unclosedInline)).toBe(unclosedInline);
  });

  it("honors odd and even backslash escaping", () => {
    expect(normalizeCjkEmphasis("\\**内容。**后")).toBe("\\**内容。**后");
    expect(normalizeCjkEmphasis("\\\\**内容。**后")).toBe("\\\\**内容**。后");
    expect(normalizeCjkEmphasis("**内容。\\**后")).toBe("**内容。\\**后");
    expect(normalizeCjkEmphasis("**内容\\\\。**后")).toBe("**内容\\\\。**后");
  });

  it("preserves matched repairs around unrelated unclosed delimiters", () => {
    expect(normalizeCjkEmphasis("**内容。**后 *未闭合")).toBe(
      "**内容**。后 *未闭合",
    );
    expect(normalizeCjkEmphasis("**甲。**乙 **未闭合")).toBe(
      "**甲**。乙 **未闭合",
    );
    expect(normalizeCjkEmphasis("*未闭合 **甲。**乙")).toBe(
      "*未闭合 **甲**。乙",
    );
  });

  it("preserves crossing invalid delimiters", () => {
    const source = "**外层 *内层。**后续";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("preserves CRLF and unfinished emphasis", () => {
    expect(normalizeCjkEmphasis("**甲。**乙\r\n__丙！__丁\r\n")).toBe(
      "**甲**。乙\r\n__丙__！丁\r\n",
    );
    for (const source of ["**未闭合。后", "_未闭合！後", "结尾 **"]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("is deterministic and idempotent", () => {
    const source = "**甲。**乙 and *丙！*丁";
    const once = normalizeCjkEmphasis(source);
    expect(normalizeCjkEmphasis(source)).toBe(once);
    expect(normalizeCjkEmphasis(once)).toBe(once);
  });

  it("leaves empty and plain text unchanged", () => {
    expect(normalizeCjkEmphasis("")).toBe("");
    const plain = "普通中文，没有任何强调标记。";
    expect(normalizeCjkEmphasis(plain)).toBe(plain);
  });
});

describe("normalizeCjkEmphasis guardrails", () => {
  it("keeps fenced code nested in a blockquote untouched", () => {
    const source = "> ~~~markdown\n> **内容。**后\n> ~~~";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps fenced code nested in a list item untouched", () => {
    const source = "- ~~~markdown\n  **内容。**后\n  ~~~";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a blockquote body working outside code fences", () => {
    expect(normalizeCjkEmphasis("> **内容。**后")).toBe("> **内容**。后");
  });

  it("keeps inline link destinations untouched", () => {
    const source = "[下载](https://example.com/中文/**版本。**后续)";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps image destinations untouched", () => {
    const source = "![图](https://example.com/中文/**版本。**后续.png)";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps reference-style link destinations untouched", () => {
    const source =
      "[下载][ref]\n\n[ref]: https://example.com/中文/**版本。**后续";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("does not create a new escape pair when punctuation moves", () => {
    expect(normalizeCjkEmphasis("**内容\\。**后")).toBe("**内容\\。**后");
    // The backslash splits the pair, so the closing run never pairs with the
    // opening one and the text stays untouched.
    expect(normalizeCjkEmphasis("**内容\\\\。**后")).toBe("**内容\\\\。**后");
  });
});

describe("normalizeCjkEmphasis container and destination guardrails", () => {
  it("does not treat a container marker inside a fence as the closing fence", () => {
    for (const marker of ["- ~~~", "> ~~~"]) {
      const source = `~~~\n${marker}\n**内容。**后\n~~~`;
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("keeps indented code inside a list item", () => {
    expect(normalizeCjkEmphasis("-     **内容。**后")).toBe(
      "-     **内容。**后",
    );
    expect(normalizeCjkEmphasis("1.     **内容。**后")).toBe(
      "1.     **内容。**后",
    );
  });

  it("keeps a reference definition inside a blockquote", () => {
    const source =
      "> [ref]: https://example.com/中文/**版本。**后续\n\n[下载][ref]";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps autolinks untouched", () => {
    for (const source of [
      "<https://example.com/**版本。**后续>",
      "<mailto:dev@example.com>",
    ]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("keeps a multi-line angle-bracket reference destination untouched", () => {
    const source =
      "[ref]: <https://example.com/\n**版本。**后续>\n\n[下载][ref]";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });
});

describe("normalizeCjkEmphasis continued-container guardrails", () => {
  it("keeps a fenced block in a continued list item", () => {
    const source = ["- item", "", "    ~~~", "  **代码。**后", "    ~~~"].join(
      "\n",
    );
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a reference destination that starts on the next line", () => {
    const source = [
      "[ref]:",
      "https://example.com/**版本。**后续",
      "",
      "[下载][ref]",
    ].join("\n");
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a reference definition nested in a list item", () => {
    const source = [
      "- [ref]: https://example.com/**版本。**后续",
      "",
      "[下载][ref]",
    ].join("\n");
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a parenthesis inside an angle-bracket destination", () => {
    const source = "[Download](<docs/)/**版本。**后续>)";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });
});

describe("normalizeCjkEmphasis nested-container guardrails", () => {
  it("keeps a blockquote fence nested in a list item", () => {
    const source = [
      "- item",
      "",
      "  > ~~~",
      "  > **代码。**后",
      "  > ~~~",
    ].join("\n");
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a list fence nested in a blockquote", () => {
    const source = [
      "> - item",
      ">",
      ">   ~~~",
      ">   **代码。**后",
      ">   ~~~",
    ].join("\n");
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a blockquote reference destination on the next line", () => {
    const source = [
      "> [ref]:",
      "> https://example.com/**版本。**后续",
      ">",
      "> [下载][ref]",
    ].join("\n");
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps a reference definition in an ordered list", () => {
    const source = [
      "1. [ref]: https://example.com/**版本。**后续",
      "",
      "[下载][ref]",
    ].join("\n");
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });
  // ---- fifth review round (zhaozhuang521, 2026-11-13) ----
  it("protects a fence nested in a quoted list item", () => {
    const source = "> - item\n>\n>     ~~~\n>   **代码。**后\n>     ~~~\n";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("protects a bare link destination", () => {
    for (const source of [
      "see https://example.com/a/**版本。**x ok",
      "see www.example.com/a/**版本。**x ok",
      "see ftp://example.com/a/**版本。**x ok",
    ]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("protects LaTeX formulas", () => {
    for (const source of [
      "in $\\text{**内容。**后}$ end",
      "in \\(\\text{**内容。**后}\\) end",
      "in $$\\text{**内容。**后}$$ end",
    ]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("protects a link title", () => {
    const source = '[下载](docs "title) **内容。**后") tail';
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("leaves a link reference definition untouched", () => {
    // The renderer does not register `marked-footnote`, so `[^1]: ...` is a
    // link reference definition: `marked` drops it from the token stream and
    // the line never reaches the reader. Rewriting it would be invisible at
    // best, and the definition text is also a link target for `[^1]`.
    const source = "ref [^1]\n\n[^1]: **内容。**后\n";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("keeps repairing text after a fence closes with its container", () => {
    const source = "> ~~~\n> **代码。**后\n> ~~~\n\n**正文。**后\n";
    expect(normalizeCjkEmphasis(source)).toBe(
      "> ~~~\n> **代码。**后\n> ~~~\n\n**正文**。后\n",
    );
  });

  it("does not read a literal bracket-paren as a link", () => {
    const source = "a]( **正文。**后\n";
    expect(normalizeCjkEmphasis(source)).toBe("a]( **正文**。后\n");
  });
});

describe("normalizeCjkEmphasis dangling-opener scope", () => {
  it("repairs a later paragraph after a lone dollar sign", () => {
    expect(normalizeCjkEmphasis("价格 $5\n\n**粗体。**后面")).toBe(
      "价格 $5\n\n**粗体**。后面",
    );
  });

  it("repairs a later paragraph after a dollar inside fenced code", () => {
    const source = "```sh\necho $HOME\n```\n\n**粗体。**后面";
    expect(normalizeCjkEmphasis(source)).toBe(
      "```sh\necho $HOME\n```\n\n**粗体**。后面",
    );
  });

  it("does not let dollars inside inline code open math", () => {
    expect(normalizeCjkEmphasis("`$PATH` 然后 **粗体。**后面")).toBe(
      "`$PATH` 然后 **粗体**。后面",
    );
  });

  it("repairs a later paragraph after a lone backtick", () => {
    expect(normalizeCjkEmphasis("a ` b\n\n**粗体。**后面")).toBe(
      "a ` b\n\n**粗体**。后面",
    );
  });

  it("repairs a later paragraph after an unterminated link", () => {
    expect(normalizeCjkEmphasis("[x](\n\n**粗体。**后面")).toBe(
      "[x](\n\n**粗体**。后面",
    );
  });

  it("protects the document after an unclosed fence with a blank line", () => {
    const source = "```md\na\n\n**代码。**后\n";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("protects the document after an unclosed tilde fence", () => {
    const source = "~~~\na\n\n**代码。**后\n";
    expect(normalizeCjkEmphasis(source)).toBe(source);
  });

  it("still skips the rest of the same paragraph", () => {
    for (const source of [
      "价格 $5 然后 **粗体。**后面",
      "a ` b 然后 **粗体。**后面",
    ]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("recognises formulas through the renderer lexer", () => {
    // A formula survives only because the lexer sees an `inlineKatex` token.
    // While the plugin was registered positionally it was silently dropped, the
    // `$...$` body came back as plain text, and its `**` delimiters were parsed
    // as emphasis and became repair candidates.
    const tokens: string[] = [];
    const walk = (list: readonly { type?: string }[]) => {
      for (const token of list) {
        if (typeof token.type === "string") tokens.push(token.type);
        const children = (token as { tokens?: { type?: string }[] }).tokens;
        if (Array.isArray(children) && children.length > 0) walk(children);
      }
    };
    walk(lexWithRenderer("$\\text{**内容。**后}$") as never);
    expect(tokens).toContain("inlineKatex");
  });

  it("stays linear across a long run of link openers", () => {
    // `firstUnclosedLink` called `lastIndexOf` once per `](`, which is
    // quadratic. 64 KiB took ~750 ms locally; the single-pass scan keeps it
    // inside a frame budget.
    const source = "](".repeat(32768) + " **content.** after";
    const startedAt = performance.now();
    normalizeCjkEmphasis(source);
    expect(performance.now() - startedAt).toBeLessThan(200);
  });

  it("keeps repairing after a bracket that only exists inside code", () => {
    // A bracket the renderer emitted as a code span is a literal character. It
    // used to truncate the editable set for every later paragraph.
    expect(normalizeCjkEmphasis("`code [ inside`\n\n**文本。**后续")).toBe(
      "`code [ inside`\n\n**文本**。后续",
    );
  });

  it("does not let an unclosed bracket stop a later paragraph", () => {
    // Counterexample 8: an unclosed `[` may not reach past its own paragraph,
    // so the independent paragraph after the blank line is still repaired.
    expect(normalizeCjkEmphasis("未闭合 [ 括号\n\n**文本。**后续")).toBe(
      "未闭合 [ 括号\n\n**文本**。后续",
    );
  });

  it("keeps a link destination embedded in emphasis", () => {
    for (const source of [
      "**[下载](https://example.com/a)**",
      "**[https://example.com/**版本。**](https://example.com/)**",
      "**见 https://example.com/**版本。****",
    ]) {
      expect(normalizeCjkEmphasis(source)).toBe(source);
    }
  });

  it("never grows the number of empty emphasis nodes", () => {
    const count = (value: string) =>
      (value.match(/\*\*\s*[.,。，、；：!?！？…]*\s*\*\*/g) ?? []).length;
    for (const source of ["**text.** **.**", "**文本。** **.**"]) {
      const fixed = normalizeCjkEmphasis(source);
      expect(count(fixed)).toBeLessThanOrEqual(count(source));
    }
  });
});

describe("normalizeCjkEmphasis rendered output", () => {
  const render = (source: string) =>
    renderToStaticMarkup(
      createElement(Markdown, { remarkPlugins: [remarkGfm] }, source),
    );

  it("turns repaired markers into real emphasis", () => {
    expect(render(normalizeCjkEmphasis("**粗体。**后面"))).toContain(
      "<strong>粗体</strong>",
    );
    expect(render(normalizeCjkEmphasis("价格 $5\n\n**粗体。**后面"))).toContain(
      "<strong>粗体</strong>",
    );
  });

  it("leaves a paired bracket literal instead of splitting the pair", () => {
    // CommonMark does not close emphasis between `)` and CJK text, exactly as
    // it refuses `**foo(bar)**baz` for ASCII parens. Moving the closing bracket
    // out of the delimiter would render `<strong>说明</strong>）` and break the
    // pair, so the source is intentionally left untouched.
    const source = "**粗体（说明）**后面";
    const fixed = normalizeCjkEmphasis(source);
    expect(fixed).toBe(source);
    expect(render(fixed)).toContain("**粗体（说明）**");
  });
});

describe("round ten review counterexamples", () => {
  /**
   * Every case asserts the repaired text and the idempotency requirement the
   * review states as `N(N(x)) === N(x)`.
   */
  const repair = (source: string, expected: string) => {
    const once = normalizeCjkEmphasis(source);
    expect(once).toBe(expected);
    expect(normalizeCjkEmphasis(once)).toBe(once);
  };

  it("keeps a link destination while repairing the label", () => {
    repair(
      "- **粗体。**后续 [Download](https://example.com/**版本。**x)",
      "- **粗体**。后续 [Download](https://example.com/**版本。**x)",
    );
  });

  it("keeps image attributes while repairing the label", () => {
    repair(
      "- **粗体。**后续 ![img](https://example.com/**版本。**.png)",
      "- **粗体**。后续 ![img](https://example.com/**版本。**.png)",
    );
  });

  it("never merges delimiters into a four-marker run", () => {
    for (const source of [
      "**内容。** followed by **。**",
      "**内容。****。**",
    ]) {
      const once = normalizeCjkEmphasis(source);
      expect(once.split("****").length - 1).toBeLessThanOrEqual(
        source.split("****").length - 1,
      );
      expect(normalizeCjkEmphasis(once)).toBe(once);
    }
  });

  it("leaves an unclosed link title untouched", () => {
    repair(
      '[a](docs "title) **标题。**后续',
      '[a](docs "title) **标题。**后续',
    );
  });

  it("protects every one of several unclosed links", () => {
    repair(
      '[a](\n\n[b](docs "**标题。**后续',
      '[a](\n\n[b](docs "**标题。**后续',
    );
  });

  it("excludes a link marker shown as code from the document scan", () => {
    repair("`[a](` **正文。**后续", "`[a](` **正文**。后续");
  });

  it("does not let an unclosed bracket stop a later paragraph", () => {
    repair("[\n\n**正文。**后续", "[\n\n**正文**。后续");
  });

  it("repairs a paragraph inside a multi-line blockquote", () => {
    repair("> 第一行\n> **正文。**后续", "> 第一行\n> **正文**。后续");
  });

  it("repairs a paragraph inside a multi-line list item", () => {
    repair("- 第一行\n  **正文。**后续", "- 第一行\n  **正文**。后续");
  });

  it("moves punctuation past a nested closing run", () => {
    repair("**bold *italic。***", "**bold *italic***。");
  });

  it("stays linear when the input is a dense run of link markers", () => {
    for (const size of [200, 1000]) {
      const body = "[a](".repeat(size) + ")".repeat(size);
      expect(normalizeCjkEmphasis(body)).toBe(body);
      const inCode = "`" + body + "`";
      expect(normalizeCjkEmphasis(inCode)).toBe(inCode);
    }
  });
});
