import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ToolCardShell from "./ToolCardShell";
import type { ToolCallContent } from "./types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

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

const imageContent = () =>
  makeContent([
    { type: "image", source: { type: "url", url: "/uploads/img.png" } },
  ]);

describe("ToolCardShell lazy media preview", () => {
  it("does not render media preview while collapsed", () => {
    render(<ToolCardShell icon={null} title="tool" content={imageContent()} />);
    expect(screen.queryByTestId("media-preview")).toBeNull();
  });

  it("renders media preview only after the card is expanded", () => {
    const { container } = render(
      <ToolCardShell icon={null} title="tool" content={imageContent()} />,
    );
    const details = container.querySelector("details") as HTMLDetailsElement;

    details.open = true;
    fireEvent(details, new Event("toggle", { bubbles: false }));

    expect(screen.getByTestId("media-preview")).toHaveTextContent("img.png");
  });

  it("passes open state to a render-function child", () => {
    const { container } = render(
      <ToolCardShell icon={null} title="tool" content={makeContent("text")}>
        {(isOpen) => (
          <div data-testid="child">{isOpen ? "open" : "closed"}</div>
        )}
      </ToolCardShell>,
    );
    expect(screen.getByTestId("child")).toHaveTextContent("closed");

    const details = container.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent(details, new Event("toggle", { bubbles: false }));

    expect(screen.getByTestId("child")).toHaveTextContent("open");
  });
});
