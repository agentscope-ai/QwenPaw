import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import LanguageBadge from "./index";

describe("LanguageBadge", () => {
  it("renders the language code inside the badge", () => {
    renderWithProviders(<LanguageBadge code="VI" />);
    expect(screen.getByText("VI")).toBeInTheDocument();
  });

  it("keeps the frame geometry measured from the real badges", () => {
    const { container } = renderWithProviders(<LanguageBadge code="ID" />);
    const rect = container.querySelector("rect");
    expect(rect).not.toBeNull();
    // Ring is 64 wide with a 152.96 radius in the real badges; the
    // centre line of that ring sits 32 units inside, so the stroked
    // rect uses 149.12 / 725.76 / 120.96 to reproduce it exactly.
    expect(rect?.getAttribute("stroke-width")).toBe("64");
    expect(rect?.getAttribute("rx")).toBe("120.96");
    expect(rect?.getAttribute("width")).toBe("725.76");
  });

  it("carries data-spark-icon so the design system sizes it", () => {
    // The design system sizes icons inside buttons with the selector
    // `span[data-spark-icon]` (20px default, 16px sm, 24px lg). Without
    // this attribute the badge falls back to the button font size and
    // renders smaller than the real language badges next to it.
    const { container } = renderWithProviders(<LanguageBadge code="ID" />);
    expect(container.querySelector("span[data-spark-icon]")).not.toBeNull();
  });
});
