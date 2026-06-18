import { describe, it, expect, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

// Mock react-window to avoid import errors in mocked ChatSessionDrawer
vi.mock("react-window", () => ({
  FixedSizeList: ({ children, itemData, itemCount }: any) => {
    const Row = children;
    return (
      <>
        {Array.from({ length: itemCount }, (_, i) => (
          <Row key={i} index={i} style={{}} data={itemData} />
        ))}
      </>
    );
  },
}));

vi.mock("../../ChatSearchPanel", () => ({ default: () => null }));
vi.mock("../../ChatSessionDrawer", () => ({ default: () => null }));

import ChatActionGroup from "./index";

describe("ChatActionGroup", () => {
  it("renders without crash", () => {
    expect(() => renderWithProviders(<ChatActionGroup />)).not.toThrow();
  });

  it("renders history icon button when onToggleHistory is provided", () => {
    renderWithProviders(<ChatActionGroup onToggleHistory={() => {}} />);
    expect(
      document.querySelector('[data-icon="SparkHistoryLine"]'),
    ).toBeInTheDocument();
  });

  it("does not render history icon button in simple mode (no onToggleHistory)", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkHistoryLine"]'),
    ).not.toBeInTheDocument();
  });

  it("renders new chat icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkNewChatFill"]'),
    ).toBeInTheDocument();
  });
});
