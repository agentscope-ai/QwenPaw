// @vitest-environment jsdom
/**
 * Contract tests for ViewImageCard.
 *
 * ViewImageCard is the image twin of ViewVideoCard and reads a different param
 * name (image_path rather than video_path). Both cards resolve their preview
 * through the same shared helper, so the param name is the only thing that can
 * silently break here: an image call would then be titled with the default text
 * and render no preview at all. Both of those are pinned below.
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
    const path = params.image_path as string | undefined;
    if (!path) return null;
    return {
      url: `file://${path}`,
      name: path.split("/").pop() ?? "",
      type: "image",
    };
  },
}));

import ViewImageCard from "./ViewImageCard";

const NO_PARAMS = undefined as unknown as Record<string, unknown>;

const createContent = (
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent => ({
  type: "tool_call",
  id: "image-1",
  name: "view_image",
  status: "done",
  params: { image_path: "/tmp/截图 2026.png" },
  result: "loaded",
  ...overrides,
});

const titleText = () => screen.getByTestId("card-title").textContent;

describe("ViewImageCard", () => {
  it("names the image file in the title", () => {
    render(<ViewImageCard content={createContent()} />);

    expect(titleText()).toBe('tool.viewImage[{"file":"截图 2026.png"}]');
  });

  it("reads image_path and not video_path", () => {
    render(
      <ViewImageCard
        content={createContent({ params: { video_path: "/tmp/clip.mp4" } })}
      />,
    );

    expect(titleText()).toBe("tool.viewImageDefault");
    expect(screen.queryByTestId("media-preview")).toBeNull();
  });

  it("falls back to the default title when the call carries no params", () => {
    render(<ViewImageCard content={createContent({ params: NO_PARAMS })} />);

    expect(titleText()).toBe("tool.viewImageDefault");
  });

  it("shows the image preview and opens the card by default", () => {
    render(<ViewImageCard content={createContent()} />);

    expect(screen.getByTestId("media-preview").textContent).toBe(
      "file:///tmp/截图 2026.png|截图 2026.png",
    );
    expect(screen.getByTestId("default-expanded").textContent).toBe("true");
  });

  it("keeps the card collapsed when nothing is previewable", () => {
    render(<ViewImageCard content={createContent({ params: {} })} />);

    expect(screen.queryByTestId("media-preview")).toBeNull();
    expect(screen.getByTestId("default-expanded").textContent).toBe("false");
    expect(screen.getByTestId("card-body").textContent).toBe("");
  });

  it("still titles the image while the call is running", () => {
    render(
      <ViewImageCard
        content={createContent({ status: "calling" })}
        isStreaming
      />,
    );

    expect(titleText()).toBe('tool.viewImage[{"file":"截图 2026.png"}]');
  });
});
