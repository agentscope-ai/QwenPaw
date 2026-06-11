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

  it("renders history icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    // Component uses lucide History icon after shadcn migration
    expect(document.querySelector(".lucide-history")).toBeInTheDocument();
  });

  it("renders new chat icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    // Component uses lucide MessageSquarePlus icon after shadcn migration
    expect(
      document.querySelector(".lucide-message-square-plus"),
    ).toBeInTheDocument();
  });
});
