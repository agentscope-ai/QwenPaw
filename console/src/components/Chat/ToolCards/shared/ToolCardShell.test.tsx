// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("./ToolCallSessionContext", () => ({
  useToolCallSessionId: () => "",
}));

vi.mock("../../../../hooks/useToolCallControl", () => ({
  useToolCallControl: () => ({
    bannerVisible: false,
    offloadRemaining: null,
    killRemaining: null,
    defaultPolicy: "keep_foreground",
    maxInternalTimeoutSecs: null,
    elapsed: 0,
    toggleBanner: vi.fn(),
    closeBanner: vi.fn(),
    updateRemaining: vi.fn(),
  }),
}));

vi.mock("./ToolCallControlPopover", () => ({
  OffloadBanner: () => null,
}));

import ToolCardShell from "./ToolCardShell";
import type { ToolCallContent } from "./types";

const content: ToolCallContent = {
  type: "tool_call",
  id: "call-1",
  name: "execute_shell_command",
  params: {},
  result: "output",
  status: "done",
};

describe("ToolCardShell lazy body", () => {
  it("keeps the full tool title available when the label is truncated", () => {
    const title = `Run ${"long-command-argument ".repeat(40)}`;

    const { container } = render(
      <ToolCardShell content={content} icon={<span />} title={title} />,
    );
    const label = container.querySelector(`[title]`);

    expect(label).not.toBeNull();
    expect(label).toHaveAttribute("title", title);
    expect(label).toHaveTextContent(title.trim());
  });

  it("mounts the body only after the first expansion", () => {
    const { container } = render(
      <ToolCardShell content={content} icon={<span />} title="Shell">
        <div>Expensive output</div>
      </ToolCardShell>,
    );

    expect(screen.queryByText("Expensive output")).not.toBeInTheDocument();

    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    details!.open = true;
    fireEvent(details!, new Event("toggle"));

    expect(screen.getByText("Expensive output")).toBeInTheDocument();

    details!.open = false;
    fireEvent(details!, new Event("toggle"));
    expect(screen.getByText("Expensive output")).toBeInTheDocument();
  });
});
