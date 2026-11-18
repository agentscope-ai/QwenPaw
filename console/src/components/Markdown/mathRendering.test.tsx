// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";

describe("Markdown math rendering", () => {
  it("renders inline and block formulas with KaTeX", () => {
    const { container } = render(
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {"Inline $E=mc^2$\n\n$$\n\\int_0^1 x\\,dx\n$$"}
      </ReactMarkdown>,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(2);
    expect(container.querySelector(".katex-display")).toBeInTheDocument();
  });

  it("keeps plain Markdown and fenced code unchanged", () => {
    const { container } = render(
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {"**Plain text**\n\n```text\n$not-math$\n```"}
      </ReactMarkdown>,
    );

    expect(container.querySelector("strong")).toHaveTextContent("Plain text");
    expect(container.querySelector(".katex")).not.toBeInTheDocument();
    expect(container.querySelector("code")).toHaveTextContent("$not-math$");
  });
});
