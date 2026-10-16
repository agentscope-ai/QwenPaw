import { fireEvent, screen } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { MarketplaceHeader } from ".";

const mocks = vi.hoisted(() => ({
  isMobile: vi.fn(() => false),
  openExternalLink: vi.fn(),
}));
vi.mock("@/hooks/useIsMobile", () => ({ useIsMobile: mocks.isMobile }));
vi.mock("@/utils/openExternalLink", () => ({
  openExternalLink: mocks.openExternalLink,
}));

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
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.isMobile.mockReturnValue(false);
  });

  it.each(["apps", "plugins", "skills"] as const)(
    "opens community inside the %s marketplace",
    (section) => {
      renderWithProviders(
        <>
          <MarketplaceHeader activeSection={section} />
          <LocationProbe />
        </>,
        { initialEntries: ["/market?tab=skills&target=pool"] },
      );
      fireEvent.click(screen.getByText("Community"));
      expect(mocks.openExternalLink).not.toHaveBeenCalled();
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/market?tab=community&target=pool",
      );
    },
  );

  it("does not add the community entrance on mobile", () => {
    mocks.isMobile.mockReturnValue(true);
    renderWithProviders(<MarketplaceHeader activeSection="apps" />);
    expect(screen.queryByText("Community")).not.toBeInTheDocument();
    expect(screen.getByText("Apps")).toBeInTheDocument();
  });

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
