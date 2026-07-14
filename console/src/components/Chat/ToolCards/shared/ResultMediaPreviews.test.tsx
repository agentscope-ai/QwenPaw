import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ResultMediaPreviews from "./ResultMediaPreviews";
import type { ToolCallContent } from "./types";

vi.mock("./MediaPreview", () => ({
  default: ({ media }: { media: { name: string } }) => (
    <div data-testid="media-preview">{media.name}</div>
  ),
}));

const makeContent = (result: unknown): ToolCallContent => ({
  type: "tool_call",
  id: "test-id",
  name: "test_tool",
  params: {},
  result,
  status: "done",
});

describe("ResultMediaPreviews", () => {
  it("renders nothing when result has no media", () => {
    const { container } = render(
      <ResultMediaPreviews content={makeContent("no media here")} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a media preview when result has an image", () => {
    render(
      <ResultMediaPreviews
        content={makeContent([
          { type: "image", source: { type: "url", url: "/uploads/img.png" } },
        ])}
      />,
    );
    expect(screen.getByTestId("media-preview")).toHaveTextContent("img.png");
  });

  it("renders multiple media previews", () => {
    render(
      <ResultMediaPreviews
        content={makeContent([
          { type: "image", source: { type: "url", url: "/uploads/a.png" } },
          { type: "video", source: { type: "url", url: "/uploads/b.mp4" } },
        ])}
      />,
    );
    expect(screen.getAllByTestId("media-preview")).toHaveLength(2);
  });
});
