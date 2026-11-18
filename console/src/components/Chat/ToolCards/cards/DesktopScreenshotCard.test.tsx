// @vitest-environment jsdom
/**
 * Contract tests for DesktopScreenshotCard.
 *
 * This card takes no params, so unlike ViewImageCard it cannot name a file: the
 * title is always the plain screenshot label. What it does decide is whether a
 * screenshot was actually captured, and that decision drives both the preview
 * and whether the card opens by default. Both are pinned here, including the
 * negative case where no image came back.
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
    defaultExpanded,
    children,
  }: {
    title?: string;
    defaultExpanded?: boolean;
    children?: React.ReactNode;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      <span data-testid="default-expanded">{String(defaultExpanded)}</span>
      <div data-testid="card-body">{children}</div>
    </div>
  ),
  MediaPreview: ({ media }: { media: { url: string; name: string } }) => (
    <div data-testid="media-preview">
      {media.url}|{media.name}
    </div>
  ),
}));

vi.mock("../shared/utils", () => ({
  getMediaInfo: (tc: ToolCallContent) => {
    if (typeof tc.result !== "string" || !tc.result.includes("/tmp/shot")) {
      return null;
    }
    return { url: "file:///tmp/shot.png", name: "shot.png", type: "image" };
  },
}));

import DesktopScreenshotCard from "./DesktopScreenshotCard";

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "shot-1",
  name: "desktop_screenshot",
  status: "done",
  params: {},
  result: "saved to /tmp/shot.png",
  ...overrides,
});

describe("DesktopScreenshotCard", () => {
  it("titles the card with the screenshot label", () => {
    render(<DesktopScreenshotCard content={createContent()} />);

    expect(screen.getByTestId("card-title").textContent).toBe(
      "tool.desktopScreenshot",
    );
  });

  it("shows the captured screenshot preview", () => {
    render(<DesktopScreenshotCard content={createContent()} />);

    expect(screen.getByTestId("media-preview").textContent).toBe(
      "file:///tmp/shot.png|shot.png",
    );
  });

  it("opens the card by default when a screenshot came back", () => {
    render(<DesktopScreenshotCard content={createContent()} />);

    expect(screen.getByTestId("default-expanded").textContent).toBe("true");
  });

  it("keeps the card collapsed when no screenshot came back", () => {
    render(
      <DesktopScreenshotCard content={createContent({ result: "failed" })} />,
    );

    expect(screen.queryByTestId("media-preview")).toBeNull();
    expect(screen.getByTestId("default-expanded").textContent).toBe("false");
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("keeps the card collapsed when the result is not text", () => {
    render(
      <DesktopScreenshotCard content={createContent({ result: { ok: 1 } })} />,
    );

    expect(screen.queryByTestId("media-preview")).toBeNull();
    expect(screen.getByTestId("default-expanded").textContent).toBe("false");
  });

  it("titles the card the same way while the capture is running", () => {
    render(
      <DesktopScreenshotCard
        content={createContent({ status: "calling", result: "" })}
        isStreaming
      />,
    );

    expect(screen.getByTestId("card-title").textContent).toBe(
      "tool.desktopScreenshot",
    );
    expect(screen.queryByTestId("media-preview")).toBeNull();
  });
});
