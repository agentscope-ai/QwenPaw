import { fireEvent, screen } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { MarketplaceHeader } from ".";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback: string) => fallback,
  }),
}));

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">{location.pathname + location.search}</div>
  );
}

describe("MarketplaceHeader", () => {
  it("switches between the existing marketplace routes", () => {
    renderWithProviders(
      <>
        <MarketplaceHeader activeSection="apps" />
        <LocationProbe />
      </>,
      { initialEntries: ["/market"] },
    );

    fireEvent.click(screen.getByText("Plugins"));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/market?tab=plugins",
    );

    fireEvent.click(screen.getByText("Skills"));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/market?tab=skills",
    );

    fireEvent.click(screen.getByText("Apps"));
    expect(screen.getByTestId("location")).toHaveTextContent("/market");
  });

  it("preserves the skill install destination while switching tabs", () => {
    renderWithProviders(
      <>
        <MarketplaceHeader activeSection="skills" />
        <LocationProbe />
      </>,
      { initialEntries: ["/market?tab=skills&target=pool"] },
    );

    fireEvent.click(screen.getByText("Plugins"));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/market?tab=plugins&target=pool",
    );

    fireEvent.click(screen.getByText("Skills"));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/market?tab=skills&target=pool",
    );
  });
});
