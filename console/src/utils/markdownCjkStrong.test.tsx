import React from "react";
import { render } from "@testing-library/react";
import { XMarkdown } from "@ant-design/x-markdown";
import { Markdown as SdkMarkdown } from "@agentscope-ai/chat";
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

  it("does not amplify ordinary emphasis that stock already parses", async () => {
    const { Marked } = await import("marked");
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

  it("reports the recovery cost against stock marked", async () => {
    const { Marked } = await import("marked");
    const build = (repeats: number) => {
      const stock = new Marked({ gfm: true });
      const patched = new Marked({ gfm: true });
      patched.use(cjkStrongExtension());
      return { stock, patched, source: "**甲。**乙".repeat(repeats) };
    };
    const time = (parse: () => void) => {
      parse();
      const t0 = performance.now();
      parse();
      return performance.now() - t0;
    };

    // Stock rejects every span here, so this input measures the recovery path
    // itself: one stock decision per recovered span. The numbers are reported
    // rather than asserted, because stock's own scan already dominates and a
    // fixed ratio would encode this machine's speed.
    const rows: string[] = [];
    for (const repeats of [200, 500, 1000]) {
      const run = build(repeats);
      const stockMs = time(() => run.stock.parse(run.source));
      const patchedMs = time(() => run.patched.parse(run.source));
      rows.push(
        `${run.source.length}B stock=${stockMs.toFixed(
          1,
        )}ms extension=${patchedMs.toFixed(1)}ms`,
      );
    }
    console.log(`recovery cost: ${rows.join(" | ")}`);
    expect(rows.length).toBe(3);
  });
});

describe("formula protection through ChatMarkdown", () => {
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
  ];

  it.each(formulaForms)(
    "keeps the %s node and payload, matching the SDK component",
    (_name, content) => {
      const sdk = render(<SdkMarkdown content={content} />);
      const app = render(<ChatMarkdown content={content} />);
      expect(sdk.container.querySelectorAll(".katex").length).toBe(1);
      expect(app.container.querySelectorAll(".katex").length).toBe(1);
      const payload = (el: HTMLElement) =>
        el.querySelector(".katex")?.textContent ?? "";
      expect(payload(app.container)).toBe(payload(sdk.container));
    },
  );

  it("keeps stock parsing when stock already produces emphasis", () => {
    const content = "**甲。**乙**丙**";
    const sdk = render(<SdkMarkdown content={content} />);
    const app = render(<ChatMarkdown content={content} />);
    // Stock nests the spans; recovery must not flatten them into siblings.
    expect(sdk.container.querySelectorAll("strong").length).toBe(2);
    expect(app.container.innerHTML).toBe(sdk.container.innerHTML);
  });
});
