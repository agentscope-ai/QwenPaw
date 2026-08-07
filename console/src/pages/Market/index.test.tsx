import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import MarketplacePage from ".";

vi.mock("../AppCenter", () => ({
  default: () => <div>apps-content</div>,
}));

vi.mock("../Settings/PluginManager", () => ({
  default: () => <div>plugins-content</div>,
}));

vi.mock("../Settings/Market/MarketPanel", () => ({
  MarketPanel: () => <div>skills-content</div>,
}));

vi.mock("./components/MarketplaceHeader", () => ({
  MarketplaceHeader: () => <div>marketplace-header</div>,
}));

describe("MarketplacePage", () => {
  it("shows apps by default", () => {
    renderWithProviders(<MarketplacePage />, { initialEntries: ["/market"] });
    expect(screen.getByText("apps-content")).toBeInTheDocument();
  });

  it("shows plugins from the shared market route", () => {
    renderWithProviders(<MarketplacePage />, {
      initialEntries: ["/market?tab=plugins"],
    });
    expect(screen.getByText("plugins-content")).toBeInTheDocument();
  });

  it("shows the skill market from the shared market route", () => {
    renderWithProviders(<MarketplacePage />, {
      initialEntries: ["/market?tab=skills"],
    });
    expect(screen.getByText("skills-content")).toBeInTheDocument();
  });
});
