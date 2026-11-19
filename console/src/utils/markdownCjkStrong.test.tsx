import React from "react";
import { render } from "@testing-library/react";
import { XMarkdown } from "@ant-design/x-markdown";
import { Markdown as SdkMarkdown } from "@agentscope-ai/chat";
import { Lexer, Marked } from "marked";
import { describe, expect, it, vi } from "vitest";

import { ChatMarkdown } from "../components/ChatMarkdown/ChatMarkdown";
import { cjkStrongExtension } from "./markdownCjkStrong";

// The shared test alias omits the vendor ConfigProvider, so provide the
// context shape `useProviderContext` expects (same stub as the other chat
// tests in this package).
vi.mock("@agentscope-ai/design", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ConfigProvider: Object.assign(() => null, {
    ConfigContext: React.createContext({
      getPrefixCls: (name: string) => name,
    }),
  }),
}));

/**
 * The CJK rule is registered as an instance-level `config` on the renderer, so
 * every assertion here goes through the real XMarkdown pipeline and inspects
 * the produced DOM — not a rewritten source string.
 */
const config = { ...cjkStrongExtension() };

function renderMarkdown(content: string) {
  const { container, rerender } = render(
    <XMarkdown content={content} config={config} />,
  );
  return { container, rerender };
}

function strongTexts(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("strong")).map(
    (node) => node.textContent ?? "",
  );
}

function visibleText(container: HTMLElement): string {
  return (container.textContent ?? "").replace(/\s+/g, " ").trim();
}

describe("CJK double emphasis through XMarkdown", () => {
  const supported: Array<[string, string]> = [
    ["**甲。**乙", "甲。"],
    ["**甲，**乙", "甲，"],
    ["**甲、**乙", "甲、"],
    ["**甲；**乙", "甲；"],
    ["**甲：**乙", "甲："],
    ["**甲！**乙", "甲！"],
    ["**甲？**乙", "甲？"],
    ["__甲。__乙", "甲。"],
    ["前 **甲。**后", "甲。"],
    ["- 列表 **甲。**后", "甲。"],
    ["> 引用 **甲。**后", "甲。"],
  ];

  it.each(supported)("renders %s", (content, expected) => {
    const { container } = renderMarkdown(content);
    expect(strongTexts(container)).toEqual([expected]);
    // The characters stay in source order: nothing is moved out of the span.
    expect(visibleText(container)).toContain(expected);
  });

  it("covers the agreed punctuation and follower families", () => {
    const punctuation = "。，、；：！？…‥·—～「」『』（）〔〕【】《》〈〉“”‘’";
    for (const mark of punctuation) {
      const content = `**甲${mark}**乙`;
      const { container } = renderMarkdown(content);
      expect(strongTexts(container), content).toEqual([`甲${mark}`]);
    }
    const followers = ["甲", "あ", "ア", "가", "豈"];
    for (const follower of followers) {
      const content = `**甲。**${follower}`;
      const { container } = renderMarkdown(content);
      expect(strongTexts(container), content).toEqual(["甲。"]);
    }
  });

  it("keeps the delimiter families it does not own", () => {
    const closers = ["_", "__", "***", "___"];
    for (const closer of closers) {
      const content = `**甲。${closer}**乙`;
      const { container } = renderMarkdown(content);
      const stock = render(<XMarkdown content={content} />);
      expect(container.innerHTML, content).toBe(stock.container.innerHTML);
    }
  });

  it("keeps surrounding text and order for a longer paragraph", () => {
    const content = "前 **甲。**后";
    const { container } = renderMarkdown(content);
    expect(visibleText(container)).toBe("前 甲。后");
  });

  it("handles several pairs in one paragraph", () => {
    const content = "**甲。**乙**丙，**丁";
    const { container } = renderMarkdown(content);
    expect(strongTexts(container)).toEqual(["甲。", "丙，"]);
    expect(visibleText(container)).toBe("甲。乙丙，丁");
  });

  it("keeps out-of-scope shapes literal", () => {
    const cases = [
      "**甲.**乙",
      "**甲。**b",
      "**甲。**1",
      "*甲。*乙",
      "_甲。_乙",
      "a__甲。__b",
      "***甲。***乙",
      "\\**甲。**乙",
    ];
    for (const content of cases) {
      const { container } = renderMarkdown(content);
      expect(strongTexts(container), content).toEqual([]);
    }
  });

  it.each([
    "***甲。**乙",
    "___甲。__乙",
    "** 甲。**乙",
    "__\u00a0甲。__乙",
    "**甲 *乙。**丙",
    "**甲 _乙_。**丙",
  ])("keeps stock output for malformed or nested runs: %s", (content) => {
    const stock = render(<XMarkdown content={content} />);
    expect(renderMarkdown(content).container.innerHTML).toBe(
      stock.container.innerHTML,
    );
  });

  it("leaves code, links, images and tables untouched", () => {
    const fence = renderMarkdown("```\n**甲。**乙\n```");
    expect(strongTexts(fence.container)).toEqual([]);
    expect(fence.container.querySelector("code")?.textContent?.trim()).toBe(
      "**甲。**乙",
    );

    const inlineCode = renderMarkdown("`**甲。**乙`");
    expect(strongTexts(inlineCode.container)).toEqual([]);
    expect(
      inlineCode.container.querySelector("code")?.textContent?.trim(),
    ).toBe("**甲。**乙");

    const link = renderMarkdown(
      "[**甲。**乙](https://example.com/path?a=1&b=2)",
    );
    const anchor = link.container.querySelector("a");
    expect(anchor?.getAttribute("href")).toBe(
      "https://example.com/path?a=1&b=2",
    );
    // Link labels share the image path (`inLink`), so they stay literal.
    expect(anchor?.textContent).toBe("**甲。**乙");

    const image = renderMarkdown(
      '![**甲。**乙](https://example.com/a.png "标题")',
    );
    const img = image.container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("https://example.com/a.png");
    expect(img?.getAttribute("alt")).toBe("**甲。**乙");
    expect(img?.getAttribute("title")).toBe("标题");

    const table = renderMarkdown(
      "| **甲。** | 乙 |\n| --- | --- |\n| **丙，** | 丁 |",
    );
    // Table cells are ordinary inline text, so the rule applies there too.
    expect(table.container.querySelector("table")).not.toBeNull();
    expect(strongTexts(table.container)).toEqual(["甲。", "丙，"]);
  });

  it("produces the same DOM on repeated renders", () => {
    const content = "前 **甲。**后 __乙，__丙";
    const first = renderMarkdown(content).container.innerHTML;
    const second = renderMarkdown(content).container.innerHTML;
    expect(second).toBe(first);
  });

  it("gives streamed and complete inputs the same final DOM", () => {
    const content = "前 **甲。**后";
    const complete = renderMarkdown(content).container.innerHTML;
    const { container, rerender } = renderMarkdown("前 **甲。");
    rerender(<XMarkdown content={content} config={config} />);
    expect(container.innerHTML).toBe(complete);
  });

  it("keeps stock parsing for already valid emphasis spans", () => {
    expect(
      strongTexts(renderMarkdown("**标准** **甲。**乙").container),
    ).toEqual(["标准", "甲。"]);
    expect(
      strongTexts(renderMarkdown("**already bold** and **甲。**乙").container),
    ).toEqual(["already bold", "甲。"]);
    expect(
      strongTexts(renderMarkdown("__标准__ __甲。__乙").container),
    ).toEqual(["标准", "甲。"]);
  });

  it("does not amplify ordinary emphasis that stock already parses", () => {
    const stock = new Marked({ gfm: true });
    const patched = new Marked({ gfm: true });
    patched.use(cjkStrongExtension());
    const source = "**ok** ".repeat(6400);
    stock.parse(source);
    patched.parse(source);
    const t0 = performance.now();
    stock.parse(source);
    const stockMs = performance.now() - t0;
    const t1 = performance.now();
    patched.parse(source);
    const patchedMs = performance.now() - t1;
    expect(patchedMs, `stock=${stockMs.toFixed(1)}ms`).toBeLessThan(
      Math.max(stockMs * 3, 50),
    );
  });

  const { emStrongRDelimAst, emStrongRDelimUnd } = Lexer.rules.inline.gfm;
  const denseCases = [
    ["**甲。**乙", "", emStrongRDelimAst, 0],
    ["**甲。**𠀀", "", emStrongRDelimAst, 0],
    ["__甲。__乙 ", "", emStrongRDelimUnd, 0],
    ["**甲。**乙", " *备注*", emStrongRDelimAst, 3],
  ] as const;

  it.each(denseCases)(
    "indexes dense %s recovery once with suffix %j",
    (span, suffix, nativeRule, maxNativeSteps) => {
      const patched = new Marked({ gfm: true }).use(cjkStrongExtension());
      for (const repeats of [500, 1000, 2000]) {
        const nativeScan = vi.spyOn(nativeRule, "exec");
        const indexScan = vi.spyOn(String.prototype, "matchAll");
        try {
          const result = patched.parse(span.repeat(repeats) + suffix) as string;
          const nativeSteps = nativeScan.mock.calls.length;
          const indexPasses = indexScan.mock.calls.filter(
            ([rule]) =>
              rule instanceof RegExp && rule.source === nativeRule.source,
          ).length;

          expect(result.match(/<strong>甲。<\/strong>/g) ?? []).toHaveLength(
            repeats,
          );
          expect(indexPasses).toBe(1);
          // The unmatched CJK delimiters do not rescan the suffix. Only the
          // trailing stock italic, if present, needs to use the native rule.
          expect(nativeSteps).toBeLessThanOrEqual(maxNativeSteps);
        } finally {
          nativeScan.mockRestore();
          indexScan.mockRestore();
        }
      }
    },
  );
});

describe("streaming CJK recovery through ChatMarkdown", () => {
  it.each([
    ["**", "*"],
    ["**", "_"],
    ["__", "*"],
    ["__", "_"],
  ])(
    "keeps %s recovery after appending an independent %s italic",
    (strongMarker, italicMarker) => {
      const partial = `${strongMarker}甲。${strongMarker}乙${"甲".repeat(
        1100,
      )}`;
      const live = render(<ChatMarkdown content={partial} />);
      expect(strongTexts(live.container)).toEqual(["甲。"]);

      for (const suffix of [italicMarker, `${italicMarker}备注`]) {
        live.rerender(<ChatMarkdown content={`${partial} ${suffix}`} />);
        expect(strongTexts(live.container)).toEqual(["甲。"]);
      }

      const complete = `${partial} ${italicMarker}备注${italicMarker}`;
      live.rerender(<ChatMarkdown content={complete} />);
      expect(strongTexts(live.container)).toEqual(["甲。"]);
      expect(live.container.querySelector("em")?.textContent).toBe("备注");
      const direct = render(<ChatMarkdown content={complete} />);
      expect(live.container.innerHTML).toBe(direct.container.innerHTML);
    },
  );

  it("indexes both delimiter families in one long paragraph", () => {
    const content = `**甲。**乙 __丙。__丁${"戊".repeat(1100)} *备注*`;
    const { container } = render(<ChatMarkdown content={content} />);
    expect(strongTexts(container)).toEqual(["甲。", "丙。"]);
    expect(container.querySelector("em")?.textContent).toBe("备注");
  });
});

describe("historical CJK boundaries through ChatMarkdown", () => {
  it.each([
    ["**内容。**𠀀", "内容。", "𠀀"],
    ["__内容。__𠀀", "内容。", "𠀀"],
    ["**内容。］**後", "内容。］", "後"],
    ["__内容！］__𠀀", "内容！］", "𠀀"],
  ])("recovers %s without moving any text", (content, strong, follower) => {
    const { container } = render(<ChatMarkdown content={content} />);
    expect(strongTexts(container)).toEqual([strong]);
    expect(container.querySelector("p")?.textContent).toBe(strong + follower);
  });

  it.each([
    "**内容］**後",
    "__内容.］__後",
    "**内容。**𐐀",
    "**内容。**😀",
    "**内容。**latin",
  ])("keeps stock rendering outside the historical cases: %s", (content) => {
    const sdk = render(<SdkMarkdown content={content} />).container;
    const app = render(<ChatMarkdown content={content} />).container;
    expect(app.innerHTML).toBe(sdk.innerHTML);
  });
});

describe("protected inline boundaries through ChatMarkdown", () => {
  it.each(["**", "__"])(
    "keeps %s around code as the paragraph grows",
    (marker) => {
      const payload = `代码。${marker}后`;
      const prefix = `${marker}甲 \`\`${payload}\`\`。${marker}后`;
      const live = render(<ChatMarkdown content={prefix} />);
      for (const length of [prefix.length, 1024, 1025, 4096]) {
        const content = prefix + "乙".repeat(length - prefix.length);
        live.rerender(<ChatMarkdown content={content} />);
        const direct = render(<ChatMarkdown content={content} />);
        expect(strongTexts(live.container), `length=${length}`).toEqual([
          `甲 ${payload}。`,
        ]);
        expect(live.container.querySelector("strong code")?.textContent).toBe(
          payload,
        );
        expect(live.container.innerHTML).toBe(direct.container.innerHTML);
        direct.unmount();
      }
    },
  );

  it.each([
    ["**", "__a", "***"],
    ["__", "**甲", "___"],
  ])(
    "uses the SDK at every length for ambiguous %s around code",
    (marker, code, tail) => {
      const prefix = `${marker}甲 \`\`${code}\`\`。${marker}后`;
      const input = (length: number) =>
        prefix + "乙".repeat(length - prefix.length - tail.length) + tail;
      const app = render(<ChatMarkdown content={input(64)} />);
      const sdk = render(<SdkMarkdown content={input(64)} />);
      for (const length of [64, 1024, 1025, 4096]) {
        const content = input(length);
        app.rerender(<ChatMarkdown content={content} />);
        sdk.rerender(<SdkMarkdown content={content} />);
        expect(app.container.innerHTML, `length=${length}`).toBe(
          sdk.container.innerHTML,
        );
        expect(app.container.querySelector("code")?.textContent).toBe(code);
      }
    },
  );

  it.each(["**。**后", "__。__后", "**！？**后", "**甲。**\u3099後"])(
    "leaves punctuation-only bodies and non-letter followers to the SDK: %s",
    (content) => {
      const sdk = render(<SdkMarkdown content={content} />).container;
      const app = render(<ChatMarkdown content={content} />).container;
      expect(sdk.querySelector("strong")).toBeNull();
      expect(app.innerHTML).toBe(sdk.innerHTML);
    },
  );

  it.each([
    ["**甲 `代码`。**后", "code", "代码", "甲 代码。"],
    ["__甲 ``代码。__后``。__后", "code", "代码。__后", "甲 代码。__后。"],
    [
      '**甲 [链接](https://example.test "标题")。**后',
      "a",
      "链接",
      "甲 链接。",
    ],
    ['__甲 [链接](/docs "标题 __甲。__后")。__后', "a", "链接", "甲 链接。"],
    ["**甲 `代码` 和 [链接](/docs)。**后", "a", "链接", "甲 代码 和 链接。"],
    [
      "**甲 `代码`。**后" + "乙".repeat(1100) + " *备注*",
      "code",
      "代码",
      "甲 代码。",
    ],
  ])(
    "recovers surrounding emphasis without changing inline nodes: %s",
    (content, selector, inlineText, strongText) => {
      const sdk = render(<SdkMarkdown content={content} />).container;
      const app = render(<ChatMarkdown content={content} />).container;
      const sdkNodes = [...sdk.querySelectorAll("a, code")];
      const appNodes = [...app.querySelectorAll("a, code")];
      expect(sdkNodes.length).toBeGreaterThan(0);
      expect(appNodes.map((node) => node.outerHTML)).toEqual(
        sdkNodes.map((node) => node.outerHTML),
      );
      expect(app.querySelector(`strong ${selector}`)?.textContent).toBe(
        inlineText,
      );
      expect(strongTexts(app)).toEqual([strongText]);
    },
  );

  it.each([
    '**甲 [链接](/docs "标题。**后") 尾',
    "**甲 ``代码。**后`` 尾",
    "**甲 `代码。**后",
    "**甲 [链接。**后](未闭合",
    "**甲 `代码` $x+1$。**后",
    "**甲 `代码` **原生**",
    "**甲。**・後",
  ])(
    "keeps the SDK result at incomplete or unsupported boundaries: %s",
    (content) => {
      const sdk = render(<SdkMarkdown content={content} />).container;
      const app = render(<ChatMarkdown content={content} />).container;
      expect(app.innerHTML).toBe(sdk.innerHTML);
    },
  );

  it("does not close inside a double-backtick code span", () => {
    const content = "**前 ``代码。**乙`` 后";
    const sdk = render(<SdkMarkdown content={content} />).container;
    const app = render(<ChatMarkdown content={content} />).container;
    expect(sdk.querySelector("code")?.textContent).toBe("代码。**乙");
    expect(app.innerHTML).toBe(sdk.innerHTML);
  });

  it.each([
    [
      "a link",
      "a",
      '[标签 [字。**乙]](https://example.test "标题")',
      { href: "https://example.test", title: "标题" },
    ],
    [
      "an image",
      "img",
      '![图 [字。**乙]](https://example.test/a.png "标题")',
      {
        src: "https://example.test/a.png",
        alt: "图 [字。**乙]",
      },
    ],
  ] as const)(
    "preserves %s with nested brackets",
    (_name, selector, inline, attributes) => {
      const content = `**前 ${inline} 后`;
      const sdk = render(<SdkMarkdown content={content} />).container;
      const app = render(<ChatMarkdown content={content} />).container;
      for (const [name, value] of Object.entries(attributes)) {
        expect(sdk.querySelector(selector)?.getAttribute(name)).toBe(value);
      }
      expect(app.innerHTML).toBe(sdk.innerHTML);
    },
  );

  it("does not close inside inline HTML", () => {
    const content = "**前 <kbd>代码。**乙</kbd> 后";
    const sdk = render(<SdkMarkdown content={content} />).container;
    const app = render(<ChatMarkdown content={content} />).container;
    expect(app.innerHTML).toBe(sdk.innerHTML);
  });

  it("does not truncate an automatically linked URL", () => {
    const content = "**前 https://example.test/甲。**乙 后";
    const sdk = render(<SdkMarkdown content={content} />).container;
    const app = render(<ChatMarkdown content={content} />).container;
    expect(sdk.querySelector("a")?.textContent).toBe(
      "https://example.test/甲。**乙",
    );
    expect(app.innerHTML).toBe(sdk.innerHTML);
  });

  it("does not close inside a strikethrough span", () => {
    const content = "**前 ~~文字。**乙~~ 后";
    const sdk = render(<SdkMarkdown content={content} />).container;
    const app = render(<ChatMarkdown content={content} />).container;
    expect(sdk.querySelector("del")?.textContent).toBe("文字。**乙");
    expect(app.innerHTML).toBe(sdk.innerHTML);
  });

  it("still recovers prose next to protected inline nodes", () => {
    const content =
      '``代码。**乙`` [链接](https://example.test "标题") **甲。**乙';
    const app = render(<ChatMarkdown content={content} />).container;
    expect(app.querySelector("code")?.textContent).toBe("代码。**乙");
    expect(app.querySelector("a")?.getAttribute("title")).toBe("标题");
    expect(strongTexts(app)).toEqual(["甲。"]);
  });

  it("keeps one formula node and its payload intact", () => {
    const content = "**前 $\\text{**公式。**后}$ 后。**续";
    const { container } = render(<ChatMarkdown content={content} />);
    expect(container.querySelectorAll(".katex").length).toBe(1);
    expect(container.textContent ?? "").toContain("公式。");
  });

  it("refuses a closer that sits inside a formula", () => {
    const content = "**甲 $公式。**乙$ 后";
    const { container } = render(<ChatMarkdown content={content} />);
    expect(container.querySelectorAll(".katex").length).toBe(1);
    expect(container.querySelectorAll("strong").length).toBe(0);
  });

  /**
   * Every formula form the configured Latex plugin accepts must keep its node
   * and its payload. The SDK component is the baseline: same input, same
   * KaTeX output. marked blanks `\(` and `\[` into `++` inside the masked
   * source, so a guard that only reads the masked copy sees no formula here.
   */
  const formulaForms: Array<[string, string]> = [
    ["$…$", "**甲 $公式。**乙$ 后"],
    ["$$…$$", "**甲 $$公式。**乙$$ 后"],
    ["\\(…\\)", "**甲 \\(公式。**乙\\) 后"],
    ["\\[…\\]", "**甲 \\[公式。**乙\\] 后"],
    ["inline code + $…$", "**甲 `\\(` $\\verb|\\)|公式。**乙$ 后"],
    ["inline code + \\[…\\]", "**甲 `\\(` \\[\\verb|\\)|公式。**乙\\] 后"],
  ];

  it.each(formulaForms)(
    "keeps the %s node and payload, matching the SDK component",
    (_name, content) => {
      const sdk = render(<SdkMarkdown content={content} />);
      const app = render(<ChatMarkdown content={content} />);
      expect(sdk.container.querySelectorAll(".katex").length).toBe(1);
      expect(app.container.innerHTML).toBe(sdk.container.innerHTML);
    },
  );

  it.each(["**甲。**乙**丙**", "**甲。**𠀀**丙**"])(
    "keeps stock parsing when stock already produces emphasis: %s",
    (content) => {
      const sdk = render(<SdkMarkdown content={content} />);
      const app = render(<ChatMarkdown content={content} />);
      // Stock nests the spans; recovery must not flatten them into siblings.
      expect(sdk.container.querySelectorAll("strong strong")).toHaveLength(1);
      expect(app.container.innerHTML).toBe(sdk.container.innerHTML);
    },
  );

  it.each([
    `**甲。**乙**${"丙".repeat(5000)}**`,
    `**甲。**乙${"甲".repeat(1100)} _备注_丙****`,
  ])("does not miss a distant stock closer (case %#)", (content) => {
    const sdk = render(<SdkMarkdown content={content} />);
    const app = render(<ChatMarkdown content={content} />);
    expect(sdk.container.querySelectorAll("strong strong")).toHaveLength(1);
    expect(app.container.innerHTML).toBe(sdk.container.innerHTML);
  });
});
