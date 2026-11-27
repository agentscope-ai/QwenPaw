import { render } from "@testing-library/react";
import { Marked } from "marked";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { XMarkdown } from "@ant-design/x-markdown";
import { describe, expect, it } from "vitest";
import {
  DOUBLE_TILDE_MARKED_CONFIG,
  DOUBLE_TILDE_REMARK_GFM_OPTIONS,
} from "./markdownStrikethrough";

describe("DOUBLE_TILDE_MARKED_CONFIG", () => {
  const parser = new Marked(DOUBLE_TILDE_MARKED_CONFIG);

  it("keeps single tildes literal in numeric ranges and prose", () => {
    const html = parser.parse(
      "range A 600~1500 t/s, range B 170~220 t/s, RAM 64~128G, ~single~",
    ) as string;

    expect(html).not.toContain("<del>");
    expect(html).toContain("600~1500 t/s");
    expect(html).toContain("170~220 t/s");
    expect(html).toContain("64~128G");
    expect(html).toContain("~single~");
  });

  it("still renders double-tilde strikethrough including inner single tildes", () => {
    const html = parser.parse(
      "~~strikethrough~~ and ~~600~1500~~ and ~~unclosed~range and ~~~triple~~~",
    ) as string;

    expect(html).toContain("<del>strikethrough</del>");
    expect(html).toContain("<del>600~1500</del>");
    expect(html).toContain("~~unclosed~range");
    expect(html).toContain("~~~triple~~~");
  });

  it("preserves single tildes inside bold, tables, code, and URLs", () => {
    const markdown = [
      "**上下文 ~128K、prefill 600~1500 t/s / ~5K t/s、decode 30~50 t/s / 170~220 t/s**",
      "",
      "| Metric | Range |",
      "| --- | --- |",
      "| prefill | 600~1500 t/s |",
      "| decode | 170~220 t/s |",
      "",
      "See https://example.com/~user and `600~1500`.",
    ].join("\n");

    const html = parser.parse(markdown) as string;

    expect(html).not.toContain("<del>");
    expect(html).toContain("<strong>");
    expect(html).toContain("600~1500 t/s");
    expect(html).toContain("170~220 t/s");
    expect(html).toContain("https://example.com/~user");
    expect(html).toContain("<code>600~1500</code>");
  });

  it("respects gfm: false when double tildes are present", () => {
    const nonGfm = new Marked({ gfm: false }, DOUBLE_TILDE_MARKED_CONFIG);
    const html = nonGfm.parse("~~not-deleted~~") as string;

    expect(html).not.toContain("<del>");
    expect(html).toContain("~~not-deleted~~");
  });

  it("applies cleanly through XMarkdown", () => {
    const { container } = render(
      <XMarkdown
        content="range A 600~1500 t/s, range B 170~220 t/s, ~~strikethrough~~"
        config={DOUBLE_TILDE_MARKED_CONFIG}
      />,
    );

    const dels = Array.from(container.querySelectorAll("del")).map(
      (node) => node.textContent,
    );
    expect(dels).toEqual(["strikethrough"]);
    expect(container.textContent).toContain("600~1500 t/s");
    expect(container.textContent).toContain("170~220 t/s");
  });
});

describe("DOUBLE_TILDE_REMARK_GFM_OPTIONS", () => {
  it("disables single-tilde strikethrough in react-markdown while keeping ~~...~~", () => {
    const { container } = render(
      <ReactMarkdown
        remarkPlugins={[[remarkGfm, DOUBLE_TILDE_REMARK_GFM_OPTIONS]]}
      >
        {"range A 600~1500 t/s, range B 170~220 t/s, RAM 64~128G, ~~removed~~"}
      </ReactMarkdown>,
    );

    const dels = Array.from(container.querySelectorAll("del")).map(
      (node) => node.textContent,
    );
    expect(dels).toEqual(["removed"]);
    expect(container.textContent).toContain("600~1500 t/s");
    expect(container.textContent).toContain("170~220 t/s");
    expect(container.textContent).toContain("64~128G");
  });
});
