// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// t() echoes the key and appends the interpolation values so the tests can tell
// which branch fired and with what arguments.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const parts = Object.entries(options)
        .filter(([k]) => k !== "detail")
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(",");
      // tool.browserUse interpolates `detail`, which is itself a translated
      // string; surface it so the action branch is observable.
      if (options.detail !== undefined) return `${key}[${options.detail}]`;
      return parts ? `${key}{${parts}}` : key;
    },
  }),
}));

vi.mock("@ant-design/icons", () => ({
  ChromeOutlined: () => <span data-testid="chrome-icon" />,
}));

// Expose the title and any output block so getBrowserTitle / formatBrowserResult
// are observable through the render.
vi.mock("../../shared", () => ({
  ToolCardShell: ({
    title,
    children,
  }: {
    title: string;
    children?: React.ReactNode;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      {children}
    </div>
  ),
  DefaultBlock: ({ content }: { content: string }) => (
    <pre data-testid="output-block">{content}</pre>
  ),
}));

// shared/utils is deliberately NOT mocked: formatBrowserResult falls back to the
// real stringifyResult, so the fallback path runs the production helper.

import BrowserUseCard, { BROWSER_TOOL_NAMES } from "./BrowserUseCard";
import type { ToolCallContent } from "../../shared/types";

function makeContent(
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent {
  return {
    type: "tool_call",
    id: "browser-1",
    name: "browser_use",
    params: {},
    status: "done",
    ...overrides,
  } as ToolCallContent;
}

function titleOf(content: ToolCallContent): string {
  render(<BrowserUseCard content={content} />);
  return screen.getByTestId("card-title").textContent ?? "";
}

describe("BROWSER_TOOL_NAMES", () => {
  it("lists every browser tool name this card claims", () => {
    expect(BROWSER_TOOL_NAMES).toBeInstanceOf(Set);
    for (const n of [
      "browser_use",
      "browser_navigate",
      "navigate",
      "browser_click",
      "click",
      "browser_type",
      "type",
      "browser_snapshot",
      "snapshot",
      "browser_scroll",
      "scroll",
    ]) {
      expect(BROWSER_TOOL_NAMES.has(n)).toBe(true);
    }
    expect(BROWSER_TOOL_NAMES.size).toBe(11);
  });

  it("does not claim unrelated tool names", () => {
    expect(BROWSER_TOOL_NAMES.has("grep_search")).toBe(false);
    expect(BROWSER_TOOL_NAMES.has("")).toBe(false);
  });
});

describe("BrowserUseCard error status", () => {
  it("renders the shell with no output block when status is error", () => {
    render(
      <BrowserUseCard
        content={makeContent({ status: "error", result: { snapshot: "x" } })}
      />,
    );
    expect(screen.getByTestId("card-title")).toBeInTheDocument();
    expect(screen.queryByTestId("output-block")).not.toBeInTheDocument();
  });
});

describe("getBrowserTitle - the browser_use action switch", () => {
  const cases: Array<[string, Record<string, unknown>, string]> = [
    [
      "start headed",
      { action: "start", headed: true },
      "tool.browserUse[tool.browserAction.startHeaded]",
    ],
    [
      "start headless",
      { action: "start" },
      "tool.browserUse[tool.browserAction.start]",
    ],
    ["stop", { action: "stop" }, "tool.browserUse[tool.browserAction.stop]"],
    [
      "open with url",
      { action: "open", url: "http://x" },
      "tool.browserUse[tool.browserAction.open{url=http://x}]",
    ],
    [
      "open default",
      { action: "open" },
      "tool.browserUse[tool.browserAction.openDefault]",
    ],
    [
      "navigate with url",
      { action: "navigate", url: "http://y" },
      "tool.browserUse[tool.browserAction.navigate{url=http://y}]",
    ],
    [
      "navigate default",
      { action: "navigate" },
      "tool.browserUse[tool.browserAction.navigateDefault]",
    ],
    [
      "navigate_back",
      { action: "navigate_back" },
      "tool.browserUse[tool.browserAction.navigateBack]",
    ],
    [
      "click with selector",
      { action: "click", selector: "#go" },
      "tool.browserUse[tool.browserAction.click{selector=#go}]",
    ],
    [
      "click via element alias",
      { action: "click", element: ".btn" },
      "tool.browserUse[tool.browserAction.click{selector=.btn}]",
    ],
    [
      "click default",
      { action: "click" },
      "tool.browserUse[tool.browserAction.clickDefault]",
    ],
    [
      "type short text",
      { action: "type", text: "hi" },
      "tool.browserUse[tool.browserAction.type{text=hi}]",
    ],
    [
      "type default",
      { action: "type" },
      "tool.browserUse[tool.browserAction.typeDefault]",
    ],
    [
      "snapshot",
      { action: "snapshot" },
      "tool.browserUse[tool.browserAction.snapshot]",
    ],
    [
      "screenshot with path",
      { action: "screenshot", path: "/p.png" },
      "tool.browserUse[tool.browserAction.screenshot{path=/p.png}]",
    ],
    [
      "screenshot default",
      { action: "screenshot" },
      "tool.browserUse[tool.browserAction.screenshotDefault]",
    ],
    [
      "eval with code",
      { action: "eval", code: "1+1" },
      "tool.browserUse[tool.browserAction.eval{code=1+1}]",
    ],
    [
      "evaluate alias",
      { action: "evaluate", code: "2" },
      "tool.browserUse[tool.browserAction.eval{code=2}]",
    ],
    [
      "eval default",
      { action: "eval" },
      "tool.browserUse[tool.browserAction.evalDefault]",
    ],
    [
      "run_code with code",
      { action: "run_code", code: "x" },
      "tool.browserUse[tool.browserAction.runCode{code=x}]",
    ],
    [
      "run_code default",
      { action: "run_code" },
      "tool.browserUse[tool.browserAction.runCodeDefault]",
    ],
    [
      "close",
      { action: "close" },
      "tool.browserUse[tool.browserAction.closePage]",
    ],
    [
      "tabs with action",
      { action: "tabs", tab_action: "next" },
      "tool.browserUse[tool.browserAction.tabs{action=next}]",
    ],
    [
      "tabs default",
      { action: "tabs" },
      "tool.browserUse[tool.browserAction.tabsDefault]",
    ],
    [
      "fill_form",
      { action: "fill_form" },
      "tool.browserUse[tool.browserAction.fillForm]",
    ],
    [
      "file_upload with filename",
      { action: "file_upload", filename: "a.txt" },
      "tool.browserUse[tool.browserAction.fileUpload{filename=a.txt}]",
    ],
    [
      "file_upload default",
      { action: "file_upload" },
      "tool.browserUse[tool.browserAction.fileUploadDefault]",
    ],
    [
      "file_download by filename",
      { action: "file_download", filename: "b.bin" },
      "tool.browserUse[tool.browserAction.fileDownload{target=b.bin}]",
    ],
    [
      "file_download by url",
      { action: "file_download", url: "http://z" },
      "tool.browserUse[tool.browserAction.fileDownload{target=http://z}]",
    ],
    [
      "file_download default",
      { action: "file_download" },
      "tool.browserUse[tool.browserAction.fileDownloadDefault]",
    ],
    [
      "press_key with key",
      { action: "press_key", key: "Enter" },
      "tool.browserUse[tool.browserAction.pressKey{key=Enter}]",
    ],
    [
      "press_key default",
      { action: "press_key" },
      "tool.browserUse[tool.browserAction.pressKeyDefault]",
    ],
    [
      "hover with selector",
      { action: "hover", selector: "#h" },
      "tool.browserUse[tool.browserAction.hover{selector=#h}]",
    ],
    [
      "hover default",
      { action: "hover" },
      "tool.browserUse[tool.browserAction.hoverDefault]",
    ],
    ["drag", { action: "drag" }, "tool.browserUse[tool.browserAction.drag]"],
    [
      "select_option",
      { action: "select_option" },
      "tool.browserUse[tool.browserAction.selectOption]",
    ],
    [
      "wait_for by text",
      { action: "wait_for", text: "ready" },
      "tool.browserUse[tool.browserAction.waitFor{target=ready}]",
    ],
    [
      "wait_for by selector",
      { action: "wait_for", selector: "#w" },
      "tool.browserUse[tool.browserAction.waitFor{target=#w}]",
    ],
    [
      "wait_for default",
      { action: "wait_for" },
      "tool.browserUse[tool.browserAction.waitForDefault]",
    ],
    [
      "resize with dims",
      { action: "resize", width: 800, height: 600 },
      "tool.browserUse[tool.browserAction.resize{w=800,h=600}]",
    ],
    [
      "resize default",
      { action: "resize" },
      "tool.browserUse[tool.browserAction.resizeDefault]",
    ],
    [
      "pdf with path",
      { action: "pdf", path: "/o.pdf" },
      "tool.browserUse[tool.browserAction.pdf{path=/o.pdf}]",
    ],
    [
      "pdf default",
      { action: "pdf" },
      "tool.browserUse[tool.browserAction.pdfDefault]",
    ],
    [
      "install",
      { action: "install" },
      "tool.browserUse[tool.browserAction.install]",
    ],
    ["batch", { action: "batch" }, "tool.browserUse[tool.browserAction.batch]"],
    [
      "unknown action falls through to the raw action",
      { action: "weird" },
      "tool.browserUse[weird]",
    ],
  ];

  it.each(cases)("titles browser_use/%s", (_label, params, expected) => {
    expect(titleOf(makeContent({ name: "browser_use", params }))).toBe(
      expected,
    );
  });

  it("truncates a long type text with an ellipsis", () => {
    const long = "a".repeat(40);
    const title = titleOf(
      makeContent({
        name: "browser_use",
        params: { action: "type", text: long },
      }),
    );
    expect(title).toContain("text=" + "a".repeat(20) + "…");
  });

  it("does not truncate a type text exactly at the limit", () => {
    const exact = "a".repeat(20);
    const title = titleOf(
      makeContent({
        name: "browser_use",
        params: { action: "type", text: exact },
      }),
    );
    expect(title).toContain("text=" + exact);
    expect(title).not.toContain("…");
  });

  it("truncates a long eval code at 30 chars", () => {
    const long = "c".repeat(50);
    const title = titleOf(
      makeContent({
        name: "browser_use",
        params: { action: "eval", code: long },
      }),
    );
    expect(title).toContain("code=" + "c".repeat(30) + "…");
  });

  it("treats a 'browser' name carrying an action like browser_use", () => {
    expect(
      titleOf(makeContent({ name: "browser", params: { action: "stop" } })),
    ).toBe("tool.browserUse[tool.browserAction.stop]");
  });

  it("resizes only when both width and height are present", () => {
    const title = titleOf(
      makeContent({
        name: "browser_use",
        params: { action: "resize", width: 800 },
      }),
    );
    expect(title).toBe("tool.browserUse[tool.browserAction.resizeDefault]");
  });
});

describe("getBrowserTitle - the standalone tool-name switch", () => {
  const cases: Array<[string, string, Record<string, unknown>, string]> = [
    [
      "browser_navigate with url",
      "browser_navigate",
      { url: "http://n" },
      "tool.browserNavigate{url=http://n}",
    ],
    [
      "navigate alias with url",
      "navigate",
      { url: "http://n2" },
      "tool.browserNavigate{url=http://n2}",
    ],
    [
      "browser_navigate default",
      "browser_navigate",
      {},
      "tool.browserNavigateDefault",
    ],
    ["browser_click", "browser_click", {}, "tool.browserClick"],
    ["click alias", "click", {}, "tool.browserClick"],
    ["browser_type", "browser_type", {}, "tool.browserType"],
    ["type alias", "type", {}, "tool.browserType"],
    ["browser_snapshot", "browser_snapshot", {}, "tool.browserSnapshot"],
    ["snapshot alias", "snapshot", {}, "tool.browserSnapshot"],
    ["browser_scroll", "browser_scroll", {}, "tool.browserScroll"],
    ["scroll alias", "scroll", {}, "tool.browserScroll"],
  ];

  it.each(cases)("titles %s", (_label, name, params, expected) => {
    expect(titleOf(makeContent({ name, params }))).toBe(expected);
  });

  it("falls back to the raw name for an unhandled tool", () => {
    expect(titleOf(makeContent({ name: "some_other_tool", params: {} }))).toBe(
      "some_other_tool",
    );
  });
});

describe("formatBrowserResult output extraction", () => {
  function outputOf(result: unknown): string | null {
    cleanup();
    render(
      <BrowserUseCard content={makeContent({ name: "snapshot", result })} />,
    );
    const block = screen.queryByTestId("output-block");
    return block ? block.textContent : null;
  }

  it("renders no output block when the result is null", () => {
    expect(outputOf(null)).toBeNull();
  });

  it("extracts snapshot and message from an object, unescaping literal newlines", () => {
    const out = outputOf({ snapshot: "line1\\nline2", message: "ok" });
    expect(out).toBe("line1\nline2\n\nok");
  });

  it("unescapes literal tab sequences in the snapshot", () => {
    expect(outputOf({ snapshot: "a\\tb" })).toBe("a\tb");
  });

  it("shows the url only when there is no snapshot", () => {
    expect(outputOf({ url: "http://u" })).toBe("URL: http://u");
    // With a snapshot present the url branch is skipped (the `!obj.snapshot`
    // guard), so only the snapshot is shown.
    expect(outputOf({ url: "http://u", snapshot: "s" })).toBe("s");
  });

  it("ignores non-string known fields and falls back to stringifyResult", () => {
    // None of snapshot/message/url are strings, so extractBrowserFields yields
    // null and the real stringifyResult pretty-prints the object.
    expect(outputOf({ snapshot: 123, message: null, url: {} })).toBe(
      JSON.stringify({ snapshot: 123, message: null, url: {} }, null, 2),
    );
  });

  it("parses a JSON object string", () => {
    expect(outputOf('{"snapshot":"s","message":"m"}')).toBe("s\n\nm");
  });

  it("parses MCP content blocks wrapping a JSON string", () => {
    const mcp = JSON.stringify([
      { type: "text", text: JSON.stringify({ snapshot: "inner" }) },
    ]);
    expect(outputOf(mcp)).toBe("inner");
  });

  it("uses an MCP text block directly when it is not JSON", () => {
    const mcp = JSON.stringify([{ type: "text", text: "plain text" }]);
    expect(outputOf(mcp)).toBe("plain text");
  });

  it("ignores MCP blocks whose type is not text", () => {
    const mcp = JSON.stringify([{ type: "image", text: '{"snapshot":"s"}' }]);
    // No text block matched, so it falls through to stringifyResult.
    expect(outputOf(mcp)).toBe(mcp);
  });

  it("falls back to stringifyResult for a non-JSON string", () => {
    expect(outputOf("just some text")).toBe("just some text");
  });

  it("falls back to stringifyResult for a malformed JSON-looking string", () => {
    expect(outputOf("{not json")).toBe("{not json");
  });

  it("falls back to stringifyResult for an object without known fields", () => {
    expect(outputOf({ other: 1 })).toBe(JSON.stringify({ other: 1 }, null, 2));
  });

  it("falls back to stringifyResult for an array result without text blocks", () => {
    // [1, 2] has no MCP text block, so extractMcpText returns null and
    // stringifyResult pretty-prints the array.
    expect(outputOf([1, 2])).toBe(JSON.stringify([1, 2], null, 2));
  });

  it("still renders a block for an empty object, since stringifyResult yields '{}'", () => {
    // {} extracts to null, but the fallback stringifyResult({}) returns "{}"
    // (not ""), which is truthy, so the output block renders.
    expect(outputOf({})).toBe("{}");
  });

  it("renders no output block when the result formats to an empty string", () => {
    // Only a result that stringifyResult turns into "" suppresses the block;
    // undefined result does exactly that.
    expect(outputOf(undefined)).toBeNull();
  });
});

describe("BrowserUseCard streaming passthrough", () => {
  it("still renders the title while streaming with no result yet", () => {
    render(
      <BrowserUseCard
        content={makeContent({
          status: "calling",
          params: { action: "snapshot" },
        })}
        isStreaming
      />,
    );
    expect(screen.getByTestId("card-title")).toHaveTextContent(
      "tool.browserAction.snapshot",
    );
    expect(screen.queryByTestId("output-block")).not.toBeInTheDocument();
  });

  it("handles missing params by defaulting to an empty object", () => {
    render(
      <BrowserUseCard
        content={{
          ...makeContent({ name: "snapshot" }),
          params: undefined as unknown as Record<string, unknown>,
        }}
      />,
    );
    expect(screen.getByTestId("card-title")).toHaveTextContent(
      "tool.browserSnapshot",
    );
  });
});
