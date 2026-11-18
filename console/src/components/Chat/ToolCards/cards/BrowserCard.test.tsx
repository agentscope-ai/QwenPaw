// @vitest-environment jsdom
/**
 * Contract tests for BrowserCard.
 *
 * Three decisions belong to this card and nowhere else:
 *  1. which browser card variant a payload routes to (legacy action payloads
 *     keep rendering through the deprecated card, everything else is unified),
 *  2. whether a failure is teaching-class guidance rather than an error, which
 *     changes how the shell paints the call,
 *  3. which of the code / output blocks the user gets to see.
 * All three are pinned here, including the two exported helpers directly.
 *
 * There was no test file for this card before this one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolCallContent } from "../shared/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? `${key}[${JSON.stringify(options)}]` : key,
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    children,
    content,
  }: {
    title?: string;
    children?: React.ReactNode;
    content?: { status?: string };
  }) => (
    <div data-testid="unified-shell" data-status={content?.status}>
      <span data-testid="card-title">{title}</span>
      {children}
    </div>
  ),
  DefaultBlock: ({
    title,
    content,
    language,
  }: {
    title?: string;
    content?: string;
    language?: string;
  }) => (
    <pre data-testid={`block-${title}`} data-language={language}>
      {content}
    </pre>
  ),
}));

vi.mock("../shared/utils", () => ({
  stringifyResult: (result: unknown) => {
    if (typeof result === "string") return result;
    return result == null ? "" : JSON.stringify(result);
  },
}));

vi.mock("./deprecated/BrowserUseCard", () => ({
  default: ({ content }: { content?: { status?: string } }) => (
    <div data-testid="legacy-browser-card" data-status={content?.status} />
  ),
}));

import BrowserCard, {
  isTeachingBrowserError,
  resolveBrowserCardVariant,
} from "./BrowserCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "browser-1",
  name: "browser",
  status: "done",
  params: {},
  ...overrides,
});

describe("resolveBrowserCardVariant", () => {
  it("routes a payload carrying an action to the legacy card", () => {
    expect(resolveBrowserCardVariant({ action: "click" })).toBe("legacy");
  });

  it("keeps an object without an action on the unified card", () => {
    expect(resolveBrowserCardVariant({ code: "await page.title()" })).toBe(
      "unified",
    );
  });

  it("keeps an empty object on the unified card", () => {
    expect(resolveBrowserCardVariant({})).toBe("unified");
  });

  it("keeps an array payload on the unified card even when it holds an action", () => {
    expect(resolveBrowserCardVariant([{ action: "click" }])).toBe("unified");
  });

  it.each([
    ["a string", "click"],
    ["a number", 7],
    ["null", null],
    ["undefined", undefined],
  ])("keeps %s on the unified card", (_label, payload) => {
    expect(resolveBrowserCardVariant(payload)).toBe("unified");
  });
});

describe("isTeachingBrowserError", () => {
  it("reads a retryable outcome as guidance", () => {
    expect(isTeachingBrowserError("[RETRYABLE] the selector moved")).toBe(true);
  });

  it("reads an ask-human outcome as guidance", () => {
    expect(isTeachingBrowserError("[ASK_HUMAN] needs credentials")).toBe(true);
  });

  it("ignores whitespace in front of the marker", () => {
    expect(isTeachingBrowserError("   [RETRYABLE] the selector moved")).toBe(
      true,
    );
  });

  it("does not read a plain failure as guidance", () => {
    expect(isTeachingBrowserError("[FAILED] page crashed")).toBe(false);
  });

  it("does not read an unmarked sentence as guidance", () => {
    expect(isTeachingBrowserError("retryable selector")).toBe(false);
  });

  it("does not read an empty result as guidance", () => {
    expect(isTeachingBrowserError("")).toBe(false);
  });
});

describe("BrowserCard", () => {
  it("routes a legacy action payload to the deprecated browser card", () => {
    render(
      <BrowserCard
        content={createContent({
          params: { action: "click", selector: "#go" },
        })}
      />,
    );

    expect(screen.getByTestId("legacy-browser-card")).toBeInTheDocument();
    expect(screen.queryByTestId("unified-shell")).toBeNull();
  });

  it("keeps a call without params on the unified card", () => {
    render(<BrowserCard content={createContent({ params: NO_PARAMS })} />);

    expect(screen.getByTestId("unified-shell")).toBeInTheDocument();
    expect(screen.queryByTestId("legacy-browser-card")).toBeNull();
  });

  it("titles the unified card with the browser tool name", () => {
    render(<BrowserCard content={createContent()} />);

    expect(screen.getByTestId("card-title").textContent).toBe(
      'tool.execute[{"tool":"browser"}]',
    );
  });

  it("shows the code the tool ran as a python block", () => {
    const code = "await page.click('#go')";
    render(<BrowserCard content={createContent({ params: { code } })} />);

    const block = screen.getByTestId("block-Code");
    expect(block.textContent).toBe(code);
    expect(block.getAttribute("data-language")).toBe("python");
  });

  it("omits the code block when the code param is not text", () => {
    render(<BrowserCard content={createContent({ params: { code: 42 } })} />);

    expect(screen.queryByTestId("block-Code")).toBeNull();
  });

  it("omits the code block when no code was sent", () => {
    render(<BrowserCard content={createContent()} />);

    expect(screen.queryByTestId("block-Code")).toBeNull();
  });

  it("shows the tool output as a text block", () => {
    render(
      <BrowserCard
        content={createContent({ result: "page title: QwenPaw" })}
      />,
    );

    const block = screen.getByTestId("block-Output");
    expect(block.textContent).toBe("page title: QwenPaw");
    expect(block.getAttribute("data-language")).toBe("text");
  });

  it("omits the output block when the tool returned nothing", () => {
    render(<BrowserCard content={createContent({ result: undefined })} />);

    expect(screen.queryByTestId("block-Output")).toBeNull();
  });

  it("paints a retryable failure as a completed call", () => {
    render(
      <BrowserCard
        content={createContent({
          status: "error",
          result: "[RETRYABLE] the selector moved",
        })}
      />,
    );

    expect(
      screen.getByTestId("unified-shell").getAttribute("data-status"),
    ).toBe("done");
  });

  it("paints an ask-human failure as a completed call", () => {
    render(
      <BrowserCard
        content={createContent({
          status: "error",
          result: "[ASK_HUMAN] needs credentials",
        })}
      />,
    );

    expect(
      screen.getByTestId("unified-shell").getAttribute("data-status"),
    ).toBe("done");
  });

  it("accepts whitespace in front of the teaching marker", () => {
    render(
      <BrowserCard
        content={createContent({
          status: "error",
          result: "  [RETRYABLE] the selector moved",
        })}
      />,
    );

    expect(
      screen.getByTestId("unified-shell").getAttribute("data-status"),
    ).toBe("done");
  });

  it("keeps a genuine failure as an error", () => {
    render(
      <BrowserCard
        content={createContent({ status: "error", result: "page crashed" })}
      />,
    );

    expect(
      screen.getByTestId("unified-shell").getAttribute("data-status"),
    ).toBe("error");
  });

  it("leaves a running call alone even when its partial output looks retryable", () => {
    render(
      <BrowserCard
        content={createContent({
          status: "calling",
          result: "[RETRYABLE] still working",
        })}
      />,
    );

    expect(
      screen.getByTestId("unified-shell").getAttribute("data-status"),
    ).toBe("calling");
  });
});
