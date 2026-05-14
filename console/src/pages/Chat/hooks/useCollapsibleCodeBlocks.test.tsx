import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";
import { useCollapsibleCodeBlocks } from "./useCollapsibleCodeBlocks";

const labels = {
  collapse: "Collapse",
  expand: "Expand",
};

function CodeBlockHarness({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const controls = useCollapsibleCodeBlocks(ref, labels);

  return (
    <div ref={ref}>
      <div className="qwenpaw-codeHighlighter">
        <div className="qwenpaw-code-header">
          <div className="qwenpaw-code-header-actions">
            <span data-testid="copy-action" />
          </div>
        </div>
        <div className="qwenpaw-codeHighlighter-code">{code}</div>
      </div>
      {controls}
    </div>
  );
}

function DynamicCodeBlockHarness() {
  const [code, setCode] = useState("line 1\nline 2");

  return (
    <>
      <button type="button" onClick={() => setCode(longCode)}>
        grow
      </button>
      <CodeBlockHarness code={code} />
    </>
  );
}

const longCode = ["one", "two", "three", "four", "five", "six"].join("\n");

describe("useCollapsibleCodeBlocks", () => {
  it("collapses long rendered code blocks by default and toggles them", async () => {
    const user = userEvent.setup();
    const { container } = render(<CodeBlockHarness code={longCode} />);

    const block = container.querySelector(".qwenpaw-codeHighlighter");
    const toggle = await screen.findByRole("button", { name: "Expand" });

    expect(block).toHaveAttribute("data-qwenpaw-code-collapsible", "true");
    expect(block).toHaveAttribute("data-qwenpaw-code-collapsed", "true");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);

    await waitFor(() =>
      expect(block).toHaveAttribute("data-qwenpaw-code-collapsed", "false"),
    );
    expect(screen.getByRole("button", { name: "Collapse" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("adds the toggle when a streaming code block grows past five lines", async () => {
    const user = userEvent.setup();
    const { container } = render(<DynamicCodeBlockHarness />);

    expect(screen.queryByRole("button", { name: "Expand" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "grow" }));

    await screen.findByRole("button", { name: "Expand" });
    expect(container.querySelector(".qwenpaw-codeHighlighter")).toHaveAttribute(
      "data-qwenpaw-code-collapsed",
      "true",
    );
  });
});
