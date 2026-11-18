import React from "react";
import ReactDOM from "react-dom";
import { readFileSync } from "node:fs";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import type {
  ChatCodeBlockProps,
  ChatRequestPayloadTransform,
} from "../src/qwenpaw-host";

afterEach(cleanup);

let Component: React.ComponentType<ChatCodeBlockProps>;
let transform: ChatRequestPayloadTransform;
const submit = vi.fn(async () => {});
const openExternalLink = vi.fn();
const disposeAll = vi.fn();
beforeEach(() => {
  submit.mockReset().mockResolvedValue(undefined);
  openExternalLink.mockClear();
});
beforeAll(async () => {
  Object.assign(window, {
    QwenPaw: {
      host: {
        React,
        ReactDOM,
        useTheme: () => "dark",
        useLocale: () => "en",
        openExternalLink,
      },
      chat: {
        disposeAll,
        submit,
        codeBlock: (
          _id: string,
          language: string,
          renderer: typeof Component,
        ) => {
          expect(language).toBe("openui-lang");
          expect(_id).toBe("qwenpaw-openui");
          Component = renderer;
          return { dispose: vi.fn() };
        },
        requestPayload: {
          add: (_id: string, fn: ChatRequestPayloadTransform) => {
            expect(_id).toBe("qwenpaw-openui");
            transform = fn;
            return { dispose: vi.fn() };
          },
        },
      },
    },
  });
  // This file is the actual release artifact: no source aliases or second React.
  const dynamicCode = vi.spyOn(globalThis, "Function");
  try {
    await import("../../dist/index.js");
    // Zod otherwise catches a blocked Function probe before falling back.
    // Verify that even this probe is avoided during schema initialization.
    expect(dynamicCode).not.toHaveBeenCalled();
  } finally {
    dynamicCode.mockRestore();
  }
});

it("loads the shipped module with host React and registers rendering plus a merging capability transform", () => {
  expect(disposeAll).toHaveBeenCalledWith("qwenpaw-openui");
  expect(Component).toBeTruthy();
  expect(
    transform!({
      payload: {
        input: [],
        request_context: {
          approval_level: "ask",
          ui_capabilities: { other: "v2" },
        },
      },
      sessionId: "s",
      selectedAgent: "a",
    }),
  ).toEqual({
    input: [],
    request_context: {
      approval_level: "ask",
      ui_capabilities: { other: "v2", openui: "v1" },
    },
  });
  const source = readFileSync("../examples/seeds.openui", "utf8");
  const Render = Component!;
  const view = render(
    <Render
      source={source}
      language="openui-lang"
      messageId="m"
      blockId="m:0"
      isStreaming={false}
      agentId="a"
      sessionId="s"
      fallback={() => <pre>fallback</pre>}
    />,
  );
  expect(screen.getByText("Total Runs: 35")).toBeTruthy();
  const styles =
    document.querySelector('style[data-qwenpaw-plugin="qwenpaw-openui"]')
      ?.textContent || "";
  expect(styles.length).toBeGreaterThan(1000);
  expect(styles).not.toMatch(/(?:^|})\s*:root\s*\{/);
  expect(
    document.querySelector("style[data-openui-theme]")?.textContent,
  ).toContain(".qwenpaw-openui");
  view.unmount();
  expect(
    document.querySelector('style[data-qwenpaw-plugin="qwenpaw-openui"]'),
  ).toBeNull();
  const prompt = readFileSync("../dist/system-prompt.txt", "utf8");
  expect(prompt).toContain("Each UI fence is an independent, complete program");
  expect(prompt).not.toContain("ONLY the changed/new statements");
  expect(prompt).not.toContain("ENTIRE response must");
  expect(prompt).not.toContain(
    "When asked about data, generate realistic/plausible data",
  );
  expect(prompt).toContain("Form(name, buttons, fields)");
  expect(prompt).toContain("second Form argument");
  expect(prompt).not.toContain("third Form argument");
  expect(prompt).toContain(
    "UI renders progressively while the fence is still open.",
  );
  expect(prompt).toContain("## Hoisting & Streaming (CRITICAL)");
  expect(prompt).toContain("included as JSON in the visible user message");
  expect(prompt).not.toMatch(
    /hidden data|mounts the completed UI|stable placeholder/,
  );
  const manifest = JSON.parse(readFileSync("../plugin.json", "utf8"));
  expect(manifest.id).toBe("qwenpaw-openui");
  expect(manifest.name).toBe("QwenPaw OpenUI");
});

function renderProgram(source: string, isStreaming = false) {
  return render(
    <Component
      source={source}
      language="openui-lang"
      messageId="m"
      blockId="m:0"
      isStreaming={isStreaming}
      agentId="a"
      sessionId="s"
      fallback={() => <pre data-testid="fallback">fallback</pre>}
    />,
  );
}

it("keeps syntax highlighting and copy behavior in standalone and Markdown code", async () => {
  const code = 'const message = "Hello";\nwindow.__openuiExecuted = true;';
  const markdown = `\`\`\`javascript\n${code}\n\`\`\``;
  const writeText = vi.fn(async () => {});
  const clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  Object.assign(window, { __openuiExecuted: false });
  try {
    const view = renderProgram(`root = Stack([
      CodeBlock("javascript", ${JSON.stringify(code)}),
      TextContent(${JSON.stringify(markdown)}),
      MarkDownRenderer(${JSON.stringify(markdown)})
    ])`);
    const blocks = view.container.querySelectorAll(
      ".openui-code-block-syntax-highlighter",
    );
    expect(blocks).toHaveLength(3);
    for (const block of blocks) {
      expect(block.textContent).toBe(code);
      expect(block.querySelector(".token.keyword")?.textContent).toBe("const");
      expect(block.querySelector(".token.string")?.textContent).toBe('"Hello"');
      // Semantic classes allow one palette to follow host theme changes.
      expect(
        block.querySelector(".token.keyword")?.getAttribute("style"),
      ).toBeNull();
    }
    for (const button of screen.getAllByRole("button", { name: "Copy code" })) {
      fireEvent.click(button);
    }
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(3));
    expect(writeText.mock.calls.every(([value]) => value === code)).toBe(true);
    expect(
      (window as unknown as { __openuiExecuted: boolean }).__openuiExecuted,
    ).toBe(false);
  } finally {
    if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard);
    else Reflect.deleteProperty(navigator, "clipboard");
  }
});

it.each([
  '@OpenUrl("https://example.com/"), @ToAssistant("Continue")',
  '@ToAssistant("Continue"), @OpenUrl("https://example.com/")',
])(
  "runs both steps in one Action and blocks a second click: %s",
  async (steps) => {
    let accept!: () => void;
    submit.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          accept = resolve;
        }),
    );
    renderProgram(`root = Stack([Button("Go", Action([${steps}]))])`);
    const button = screen.getByRole("button", { name: "Go" });
    // Keep both gestures in one React batch: the ref guard must work before
    // disabled={pending} has committed to the DOM.
    act(() => {
      button.click();
      button.click();
    });
    expect(openExternalLink).toHaveBeenCalledExactlyOnceWith(
      "https://example.com/",
    );
    expect(submit).toHaveBeenCalledExactlyOnceWith("qwenpaw-openui", {
      agentId: "a",
      sessionId: "s",
      query: "Continue",
    });
    expect(screen.getByRole("status").textContent).toBe("Submitting…");
    await act(async () => accept());
    expect(screen.queryByRole("status")).toBeNull();
  },
);

it("retains every submission in one Action and stays pending until all settle", async () => {
  let first!: () => void;
  let second!: () => void;
  submit.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        first = resolve;
      }),
  );
  submit.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        second = resolve;
      }),
  );
  renderProgram(
    'root = Stack([Button("Go", Action([@ToAssistant("First"), @ToAssistant("Second")]))])',
  );
  fireEvent.click(screen.getByRole("button", { name: "Go" }));
  expect(submit).toHaveBeenCalledTimes(2);
  await act(async () => first());
  expect(screen.getByRole("status")).toBeTruthy();
  await act(async () => second());
  expect(screen.queryByRole("status")).toBeNull();
});

// Exercise the release artifact, including the upstream parser and renderer.
// Testing prompt wording alone cannot establish these execution boundaries.
const maliciousPrograms = [
  "<script>window.__openuiExecuted = true</script>",
  "root = TextContent(window.location.href)",
  'root = TextContent(@Function("window.__openuiExecuted = true")())',
  'root = TextContent(@eval("window.__openuiExecuted = true"))',
  'root = TextContent(data.constructor.constructor("return window")())\ndata = {}',
  'root = Html("<img src=x onerror=alert(1)>")',
  'root = Button("Run", @Eval("alert(1)"))',
  'root = TextContent(result)\nresult = Query("fetch", {url: "https://example.com/"})',
  'root = TextContent(result)\nresult = Mutation("fetch", {url: "https://example.com/"})',
];

it.each(maliciousPrograms)(
  "never executes a program during streaming or replay: %s",
  async (source) => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    Object.assign(window, { __openuiExecuted: false });
    try {
      const view = renderProgram("", true);
      for (let i = 1; i <= source.length; i++) {
        view.rerender(
          <Component
            source={source.slice(0, i)}
            language="openui-lang"
            messageId="m"
            blockId="m:0"
            agentId="a"
            sessionId="s"
            isStreaming
            fallback={() => null}
          />,
        );
      }
      view.unmount();
      renderProgram(source);
      expect(await screen.findByRole("alert")).toBeTruthy();
      expect(
        document.querySelector("script, iframe, [onerror], [onclick]"),
      ).toBeNull();
      expect(
        (window as unknown as { __openuiExecuted: boolean }).__openuiExecuted,
      ).toBe(false);
      expect(fetch).not.toHaveBeenCalled();
      expect(open).not.toHaveBeenCalled();
      expect(submit).not.toHaveBeenCalled();
      expect(openExternalLink).not.toHaveBeenCalled();
    } finally {
      fetch.mockRestore();
      open.mockRestore();
    }
  },
);

it.each(["TextContent", "MarkDownRenderer"])(
  "keeps HTML and event handlers inert inside %s",
  (component) => {
    const markup =
      '<img src="x" onerror="window.__openuiExecuted=true"><script>window.__openuiExecuted=true</script>';
    renderProgram(`root = ${component}(${JSON.stringify(markup)})`);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.querySelector("script, img, iframe, [onerror]")).toBeNull();
  },
);

const unsafeUrls = [
  "javascript:alert(1)",
  "JaVaScRiPt:alert(1)",
  "java\tscript:alert(1)",
  "\n javascript:alert(1)",
  "data:text/html,<script>alert(1)</script>",
  "vbscript:msgbox(1)",
  "file:///tmp/example.html",
];

it.each(unsafeUrls)("rejects an unsafe OpenUrl action: %j", async (url) => {
  renderProgram(`root = Button("Open", @OpenUrl(${JSON.stringify(url)}))`);
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(openExternalLink).not.toHaveBeenCalled();
  expect(submit).not.toHaveBeenCalled();
});

it.each(unsafeUrls)("keeps unsafe component links inert: %j", (url) => {
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  try {
    const view = renderProgram(
      `root = EditableTable("links", [{type: "url", key: "url", header: "Link"}], [{id: "1", values: [${JSON.stringify(
        url,
      )}]}])`,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      view.container.querySelector(".openui-editable-table-display-url")
        ?.textContent,
    ).toBe(url);
    for (const link of view.container.querySelectorAll("a")) {
      expect(link.getAttribute("href")).toBeFalsy();
      fireEvent.click(link);
    }
    expect(open).not.toHaveBeenCalled();
  } finally {
    open.mockRestore();
  }
});

it.each([
  "javascript:alert",
  "data:text/html,unsafe",
  "vbscript:alert",
  "file:///tmp/test",
  "java&#x09;script:alert",
])("strips unsafe Markdown destinations: %s", (url) => {
  const text = `[Unsafe](${url})`;
  renderProgram(`root = MarkDownRenderer(${JSON.stringify(text)})`);
  expect(screen.queryByRole("alert")).toBeNull();
  const link = screen.getByText("Unsafe");
  expect(link.tagName).toBe("A");
  expect(link.getAttribute("href")).toBeFalsy();
});

it("still evaluates official local functions and submits their results", async () => {
  renderProgram(
    'root = Stack([TextContent("Total: " + @Sum([1, 2, 3])), Button("Continue", @ToAssistant("Total: " + @Sum([1, 2, 3])))])',
  );
  expect(screen.getByText("Total: 6")).toBeTruthy();
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() =>
    expect(submit).toHaveBeenCalledExactlyOnceWith("qwenpaw-openui", {
      agentId: "a",
      sessionId: "s",
      query: "Total: 6",
    }),
  );
  expect(openExternalLink).not.toHaveBeenCalled();
});

it("renders and submits the Form argument order advertised in the generated prompt", async () => {
  renderProgram(`root = Stack([form])
form = Form("registration", buttons, [field])
buttons = Buttons([Button("Submit", @ToAssistant("Register"))])
field = FormControl("Name", Input("name", "Your name"))`);
  expect(screen.queryByTestId("fallback")).toBeNull();
  fireEvent.change(screen.getByPlaceholderText("Your name"), {
    target: { value: "Ada" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Submit" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  const call = submit.mock.calls[0] as unknown as [string, { query: string }];
  expect(call[1].query).toContain('"name": "Ada"');
});

const tabs =
  'Tabs([TabItem("a", "Tab A", [TextContent("Panel A")]), TabItem("b", "Tab B", [TextContent("Panel B")])])';

it.each([
  "root = Stack([heading, tabs])\ntabs = " + tabs,
  "root = Stack([card])\ncard = Card([heading, tabs])\ntabs = " + tabs,
  "root = Stack([heading, " + tabs + "])",
])(
  "keeps interactive children mounted when a preceding reference resolves: %s",
  (source) => {
    const props: ChatCodeBlockProps = {
      source,
      language: "openui-lang",
      messageId: "m",
      blockId: "m:0",
      isStreaming: true,
      agentId: "a",
      sessionId: "s",
      fallback: () => <pre>fallback</pre>,
    };
    const view = render(<Component {...props} />);
    const tabA = screen.getByRole("tab", { name: "Tab A" });
    fireEvent.mouseDown(tabA, { button: 0, ctrlKey: false });
    tabA.focus();
    expect(tabA.getAttribute("aria-selected")).toBe("true");
    const tail = '\nheading = TextContent("Arrived later")\n';
    for (let i = 1; i <= tail.length; i++) {
      view.rerender(
        <Component {...props} source={source + tail.slice(0, i)} />,
      );
      expect(screen.getByRole("tab", { name: "Tab A" })).toBe(tabA);
      expect(tabA.getAttribute("aria-selected")).toBe("true");
      expect(document.activeElement).toBe(tabA);
    }
    expect(screen.getByText("Arrived later")).toBeTruthy();
    view.rerender(
      <Component {...props} source={source + tail} isStreaming={false} />,
    );
    expect(screen.getByRole("tab", { name: "Tab A" })).toBe(tabA);
    expect(tabA.getAttribute("aria-selected")).toBe("true");
    expect(submit).not.toHaveBeenCalled();
  },
);

it("keeps repeated references as independent instances while earlier siblings arrive", () => {
  const source = "root = Stack([heading, tabs, tabs])\ntabs = " + tabs;
  const props: ChatCodeBlockProps = {
    source,
    language: "openui-lang",
    messageId: "m",
    blockId: "m:0",
    isStreaming: true,
    agentId: "a",
    sessionId: "s",
    fallback: () => null,
  };
  const view = render(<Component {...props} />);
  const before = screen.getAllByRole("tab", { name: "Tab A" });
  fireEvent.mouseDown(before[0], { button: 0, ctrlKey: false });
  expect(before[0].getAttribute("aria-selected")).toBe("true");
  expect(before[1].getAttribute("aria-selected")).toBe("false");
  view.rerender(
    <Component
      {...props}
      source={source + '\nheading = TextContent("Hello")'}
    />,
  );
  const after = screen.getAllByRole("tab", { name: "Tab A" });
  expect(after[0]).toBe(before[0]);
  expect(after[1]).toBe(before[1]);
  expect(after[0].getAttribute("aria-selected")).toBe("true");
  expect(after[1].getAttribute("aria-selected")).toBe("false");
});
