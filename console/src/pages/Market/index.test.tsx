import { fireEvent, screen } from "@testing-library/react";
import { useNavigate } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { MarketResult } from "@/api/modules/market";
import { renderWithProviders } from "@/test/common_setup";
import MarketplacePage from ".";

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: (selector: (state: { selectedAgent: string }) => unknown) =>
    selector({ selectedAgent: "agent-1" }),
}));

vi.mock("../Settings/Market/useMarketInstall", async () => {
  const { useState } = await import("react");
  return {
    useMarketInstall: () => {
      const [queue, setQueue] = useState<unknown[]>([]);
      return {
        queue,
        enqueue: (results: unknown[]) => setQueue(results),
        cancel: vi.fn(),
        retry: vi.fn(),
        clearFinished: vi.fn(),
      };
    },
  };
});

vi.mock("../AppCenter", () => ({
  default: () => <div>apps-content</div>,
}));

vi.mock("../Settings/PluginManager", () => ({
  default: () => <div>plugins-content</div>,
}));

vi.mock("../Settings/Market/MarketPanel", () => ({
  MarketPanel: ({
    installTarget,
    install,
  }: {
    installTarget: "pool" | "workspace";
    install: { enqueue: (results: MarketResult[]) => void };
  }) => (
    <div>
      skills-content
      <span data-testid="skill-market-target">{installTarget}</span>
      <button
        onClick={() =>
          install.enqueue([
            {
              source: "qwenpaw",
              slug: "test-skill",
              name: "Test Skill",
              source_url: "https://example.com/test-skill.zip",
            } as MarketResult,
          ])
        }
      >
        enqueue-skill
      </button>
    </div>
  ),
  InstallQueuePanel: ({ queue }: { queue: unknown[] }) => (
    <div data-testid="install-queue">{queue.length}</div>
  ),
}));

vi.mock("./components/MarketplaceHeader", () => ({
  MarketplaceHeader: () => <div>marketplace-header</div>,
}));

function NavigationControls() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate("/market")}>go-apps</button>
      <button onClick={() => navigate("/market?tab=plugins")}>
        go-plugins
      </button>
    </>
  );
}

function renderMarketplace(initialEntry: string, withNavigation = false) {
  return renderWithProviders(
    <>
      <MarketplacePage />
      {withNavigation && <NavigationControls />}
    </>,
    { initialEntries: [initialEntry] },
  );
}

describe("MarketplacePage", () => {
  it("shows apps by default", () => {
    renderMarketplace("/market");
    expect(screen.getByText("apps-content")).toBeInTheDocument();
  });

  it("shows plugins from the shared market route", () => {
    renderMarketplace("/market?tab=plugins");
    expect(screen.getByText("plugins-content")).toBeInTheDocument();
  });

  it("shows the skill market from the shared market route", () => {
    renderMarketplace("/market?tab=skills");
    expect(screen.getByText("skills-content")).toBeInTheDocument();
    expect(screen.getByTestId("skill-market-target")).toHaveTextContent(
      "workspace",
    );
  });

  it("keeps pool installs when the market is opened from Skill Pool", () => {
    renderMarketplace("/market?tab=skills&target=pool");
    expect(screen.getByTestId("skill-market-target")).toHaveTextContent("pool");
  });

  it("keeps the skill install queue while switching tabs", () => {
    renderMarketplace("/market?tab=skills", true);
    fireEvent.click(screen.getByText("enqueue-skill"));
    expect(screen.getByTestId("install-queue")).toHaveTextContent("1");

    fireEvent.click(screen.getByText("go-apps"));
    expect(screen.queryByText("skills-content")).not.toBeInTheDocument();
    expect(screen.getByTestId("install-queue")).toHaveTextContent("1");

    fireEvent.click(screen.getByText("go-plugins"));
    expect(screen.getByTestId("install-queue")).toHaveTextContent("1");
  });
});
