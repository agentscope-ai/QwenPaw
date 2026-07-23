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
