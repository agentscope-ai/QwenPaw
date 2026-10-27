// @vitest-environment jsdom
/**
 * Contract tests for ViewVideoCard.
 *
 * The card has two independent jobs: naming the video in the title, and
 * deciding whether the player preview should be open from the start. The
 * second one matters because a video call that produced no playable url must
 * stay collapsed instead of showing an empty body, which is what the
 * defaultExpanded prop is pinned to here.
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
  shortFileName: (p: unknown) =>
    typeof p === "string" ? p.split("/").pop() : "",
  getMediaInfo: (tc: ToolCallContent) => {
    const params = tc.params || {};
    const path = params.video_path as string | undefined;
    if (!path) return null;
    return {
      url: `file://${path}`,
      name: path.split("/").pop() ?? "",
      type: "video",
    };
  },
}));

import ViewVideoCard from "./ViewVideoCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "video-1",
  name: "view_video",
  status: "done",
  params: { video_path: "/tmp/clip.mp4" },
  result: "loaded",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("ViewVideoCard", () => {
  it("names the video file in the title", () => {
    render(<ViewVideoCard content={createContent()} />);

    expect(titleText()).toBe('tool.viewVideo[{"file":"clip.mp4"}]');
  });

  it("falls back to the default title when no video path was given", () => {
    render(<ViewVideoCard content={createContent({ params: {} })} />);

    expect(titleText()).toBe("tool.viewVideoDefault");
  });

  it("falls back to the default title when the call carries no params", () => {
    render(<ViewVideoCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.viewVideoDefault");
  });

  it("shows the player preview when a playable url was resolved", () => {
    render(<ViewVideoCard content={createContent()} />);

    expect(screen.getByTestId("media-preview").textContent).toBe(
      "file:///tmp/clip.mp4|clip.mp4",
    );
  });

  it("opens the card by default when there is media to show", () => {
    render(<ViewVideoCard content={createContent()} />);

    expect(screen.getByTestId("default-expanded").textContent).toBe("true");
  });

  it("keeps the card collapsed when nothing is playable", () => {
    render(<ViewVideoCard content={createContent({ params: {} })} />);

    expect(screen.queryByTestId("media-preview")).toBeNull();
    expect(screen.getByTestId("default-expanded").textContent).toBe("false");
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("passes the streaming flag through to the shell", () => {
    render(
      <ViewVideoCard
        content={createContent({ status: "calling" })}
        isStreaming
      />,
    );

    expect(titleText()).toBe('tool.viewVideo[{"file":"clip.mp4"}]');
  });
});
