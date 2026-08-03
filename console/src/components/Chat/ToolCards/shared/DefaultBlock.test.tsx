/**
 * Tests for DefaultBlock Output copy button.
 */
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@agentscope-ai/chat", () => ({
  Markdown: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

vi.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: string }) => (
    <pre data-testid="syntax">{children}</pre>
  ),
}));

vi.mock("react-syntax-highlighter/dist/esm/styles/prism", () => ({
  oneDark: {},
}));

const { copyTextMock } = vi.hoisted(() => ({
  copyTextMock: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/utils/clipboard", () => ({
  copyText: copyTextMock,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

import DefaultBlock from "./DefaultBlock";
import * as clipboard from "@/utils/clipboard";

describe("DefaultBlock copy", () => {
  beforeEach(() => {
    copyTextMock.mockReset();
    copyTextMock.mockResolvedValue(undefined);
  });

  it("copies output content through copyText helper", async () => {
    expect(clipboard.copyText).toBe(copyTextMock);

    render(<DefaultBlock title="Output" content={"Table 0\nRow 0"} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(copyTextMock).toHaveBeenCalledTimes(1);
    });
    expect(copyTextMock).toHaveBeenCalledWith("Table 0\nRow 0");
  });

  it("shows copied state after copyText resolves", async () => {
    render(<DefaultBlock title="Output" content="shell output body" />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(screen.getByLabelText("check")).toBeInTheDocument();
    });
  });
});

describe("DefaultBlock large output", () => {
  beforeEach(() => {
    copyTextMock.mockReset();
    copyTextMock.mockResolvedValue(undefined);
  });

  const makeLines = (count: number) =>
    Array.from({ length: count }, (_, i) => `line-${i + 1}`).join("\n");

  it("keeps syntax highlighting for small content", () => {
    render(<DefaultBlock title="Output" content={makeLines(10)} />);
    expect(screen.getByTestId("syntax")).toBeInTheDocument();
  });

  it("renders many-line output as plain text with head and tail", () => {
    const content = makeLines(2001);
    render(<DefaultBlock title="Output" content={content} />);

    // No syntax highlighter for large content
    expect(screen.queryByTestId("syntax")).not.toBeInTheDocument();
    // Head and tail lines are present
    expect(screen.getByText(/line-1\b/)).toBeInTheDocument();
    expect(screen.getByText(/line-2001/)).toBeInTheDocument();
    // Omitted notice with the omitted line count (2001 - 200 - 300)
    expect(
      screen.getByText(/tool\.largeOutputOmitted:1501/),
    ).toBeInTheDocument();
  });

  it("does not leak the stdout marker in large output", () => {
    const content = `Command failed with exit code 1.\n[stdout]\n${makeLines(
      2001,
    )}`;
    const { container } = render(
      <DefaultBlock title="Output" content={content} />,
    );

    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.textContent).not.toContain("[stdout]");
    expect(pre?.textContent).toContain("Command failed with exit code 1.");
    expect(pre?.textContent).toContain("line-2001");
  });

  it("renders one giant line as plain text without highlighting", () => {
    const content = "x".repeat(150_000);
    const { container } = render(
      <DefaultBlock title="Output" content={content} />,
    );
    expect(screen.queryByTestId("syntax")).not.toBeInTheDocument();

    expect(screen.getByText(/tool\.largeOutputTruncated/)).toBeInTheDocument();
    const pre = container.querySelector("pre");
    expect(pre?.textContent?.startsWith("x".repeat(32_000))).toBe(true);
  });

  it("copy still copies the full content in large mode", async () => {
    const content = makeLines(2001);
    render(<DefaultBlock title="Output" content={content} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(copyTextMock).toHaveBeenCalledTimes(1);
    });
    expect(copyTextMock).toHaveBeenCalledWith(content);
  });
});
