// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      key: string,
      opts?: { pattern?: string; count?: number; path?: string },
    ) => {
      if (opts?.pattern) return `${key}:${opts.pattern}`;
      if (opts?.count !== undefined) return `${key}:${opts.count}`;
      if (opts?.path) return `${key}:${opts.path}`;
      return key;
    },
  }),
}));

vi.mock("../../../../stores/projectDirectoryStore", () => ({
  useProjectDir: () => ({
    projectDir: "/Users/demo/project",
    setProjectDir: () => {},
  }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    children,
    title,
    summaryAction,
    defaultExpanded,
  }: {
    children?: React.ReactNode;
    title?: string;
    summaryAction?: React.ReactNode;
    defaultExpanded?: boolean;
  }) => (
    <div data-expanded={String(Boolean(defaultExpanded))}>
      <div>{title}</div>
      {summaryAction}
      {children}
    </div>
  ),
  DefaultBlock: ({ content }: { content: string }) => (
    <pre data-testid="default-block">{content}</pre>
  ),
}));

vi.mock("../shared/utils", async () => {
  const actual = await vi.importActual<typeof import("../shared/utils")>(
    "../shared/utils",
  );
  return {
    ...actual,
  };
});

import GrepSearchCard from "./GrepSearchCard";

const multiFileResult = [
  "src/main.py:12:> def main():",
  "src/main.py:13:  pass",
  "src/util.py:3:> def main_helper():",
].join("\n");

function openPreviewAndClick(label: string) {
  fireEvent.click(screen.getByRole("button", { name: "tool.grepResults" }));
  fireEvent.click(screen.getByRole("button", { name: label }));
}

describe("GrepSearchCard", () => {
  it("keeps raw Output visible and hides the clickable list until results are opened", () => {
    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-1",
          name: "grep_search",
          status: "done",
          params: { pattern: "def main", show_file: true },
          result: multiFileResult,
        }}
      />,
    );

    expect(screen.getByTestId("default-block")).toHaveTextContent(
      "src/main.py:12:> def main():",
    );
    expect(
      screen.queryByRole("button", { name: "src/main.py" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "tool.grepResults" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles an isolated clickable result panel from the results action", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-1",
          name: "grep_search",
          status: "done",
          params: { pattern: "def main", show_file: true },
          result: multiFileResult,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "tool.grepResults" }));
    expect(
      screen.getByRole("button", { name: "tool.grepResults" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("default-block")).toBeInTheDocument();

    const mainRow = screen.getByRole("button", { name: "src/main.py" });
    expect(mainRow).toHaveTextContent("main.py");
    fireEvent.click(mainRow);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({
      path: "src/main.py",
      line: 12,
      root: "project",
    });
    expect((listener.mock.calls[0][0] as CustomEvent).detail.workspace).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", { name: "tool.grepResults" }));
    expect(
      screen.queryByRole("button", { name: "src/main.py" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("default-block")).toBeInTheDocument();

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("expands a file group so each match line can open a different target", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-multi",
          name: "grep_search",
          status: "done",
          params: { pattern: "def main" },
          result: [
            "src/main.py:12:> def main():",
            "src/main.py:40:> def main_helper():",
          ].join("\n"),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "tool.grepResults" }));
    expect(
      screen.getByRole("button", { name: "src/main.py" }),
    ).toHaveTextContent("2");

    fireEvent.click(
      screen.getByRole("button", { name: "tool.grepExpandFile:src/main.py" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "src/main.py:40" }));
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({
      path: "src/main.py",
      line: 40,
    });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("opens params.path for single-file basename display paths", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-file",
          name: "grep_search",
          status: "done",
          params: { pattern: "hit", path: "src/foo.py" },
          result: "foo.py:12:> hit",
        }}
      />,
    );

    openPreviewAndClick("src/foo.py");
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({ path: "src/foo.py", line: 12 });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("joins directory params.path with display paths before opening", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-dir",
          name: "grep_search",
          status: "done",
          params: { pattern: "helper", path: "src" },
          result: "util.py:3:> helper",
        }}
      />,
    );

    openPreviewAndClick("src/util.py");
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({ path: "src/util.py", line: 3 });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("opens single-file show_file=False results using params.path", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-nofile",
          name: "grep_search",
          status: "done",
          params: { pattern: "two", path: "src/foo.py", show_file: false },
          result: "2:> line two",
        }}
      />,
    );

    openPreviewAndClick("src/foo.py");
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({ path: "src/foo.py", line: 2 });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("maps absolute params.path through the project directory before opening", () => {
    const listener = vi.fn();
    window.addEventListener("qwenpaw:open-file-preview", listener);

    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-abs",
          name: "grep_search",
          status: "done",
          params: {
            pattern: "hit",
            path: "/Users/demo/project/src/foo.py",
          },
          result: "foo.py:9:> hit",
        }}
      />,
    );

    openPreviewAndClick("src/foo.py");
    expect(
      (listener.mock.calls[0][0] as CustomEvent).detail.target,
    ).toMatchObject({ path: "src/foo.py", line: 9 });

    window.removeEventListener("qwenpaw:open-file-preview", listener);
  });

  it("does not show results action when there are no openable paths", () => {
    render(
      <GrepSearchCard
        content={{
          type: "tool_call",
          id: "grep-2",
          name: "grep_search",
          status: "done",
          params: { pattern: "zzz" },
          result: "No matches found for pattern: zzz",
        }}
      />,
    );

    expect(screen.getByTestId("default-block")).toHaveTextContent(
      "No matches found for pattern: zzz",
    );
    expect(
      screen.queryByRole("button", { name: "tool.grepResults" }),
    ).not.toBeInTheDocument();
  });
});
