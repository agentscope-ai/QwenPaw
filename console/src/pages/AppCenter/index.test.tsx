// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation } from "react-router-dom";

import { renderWithProviders } from "@/test/common_setup";
import AppCenterPage from "./index";

const hoisted = vi.hoisted(() => ({
  listApps: vi.fn(),
  uninstall: vi.fn(),
  fetchMarketPlugins: vi.fn(),
  installPlugin: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  // Required by src/i18n.ts, pulled in through ChunkErrorBoundary.
  initReactI18next: { type: "3rdParty", init: vi.fn() },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({ current }: { current: string }) => <div>{current}</div>,
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { loading: vi.fn(), success: vi.fn(), error: vi.fn() },
  }),
}));

vi.mock("@/api/modules/pawapp", () => ({
  pawappApi: {
    list: hoisted.listApps,
    uninstall: hoisted.uninstall,
  },
}));

vi.mock("@/plugins/registry/hooks", () => ({
  useRoutes: () => [],
}));

vi.mock("@/api/modules/pluginMarket", async () => {
  const actual = await vi.importActual<
    typeof import("@/api/modules/pluginMarket")
  >("@/api/modules/pluginMarket");
  return {
    ...actual,
    fetchMarketPlugins: hoisted.fetchMarketPlugins,
  };
});

vi.mock("@/api/modules/plugin", () => ({
  installPlugin: hoisted.installPlugin,
}));

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">{location.pathname + location.search}</div>
  );
}

function makeApp(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: id,
    version: "1.0.0",
    description: `${id} description`,
    author: "dev",
    category: "tools",
    icon: "",
    status: "active",
    home_page: null,
    entry_page: `/apps/${id}`,
    launch_scope: "page",
    dir: `/tmp/${id}`,
    settings: [],
    permissions: {},
    backends: {},
    ...overrides,
  };
}

function renderPage(initialEntries: string[] = ["/apps"]) {
  return renderWithProviders(
    <>
      <AppCenterPage />
      <LocationProbe />
    </>,
    { initialEntries },
  );
}

describe("AppCenterPage", () => {
  beforeEach(() => {
    hoisted.listApps.mockReset();
    hoisted.uninstall.mockReset();
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    hoisted.listApps.mockResolvedValue({
      apps: [makeApp("alpha-app"), makeApp("beta-app", { category: "games" })],
      total: 2,
    });
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
    window.history.replaceState({}, "", "/apps");
  });

  it("renders installed apps by default without mounting external views", async () => {
    renderPage();

    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
    expect(screen.getByText("beta-app")).toBeInTheDocument();

    // Neither market channel may load on /apps.
    expect(
      screen.queryByLabelText("appCenter.searchMarket"),
    ).not.toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).not.toHaveBeenCalled();
  });

  it("enters the official view and loads featured apps lazily", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [
        {
          id: "agent-kanban",
          display_name: "Agent Kanban",
          developer: "zhijianma",
          owner: "zhijianma",
          version: "0.1.0",
          logo_url: null,
          downloads: 1536,
          view_count: 1266,
          details_url: null,
          locales: { en: { description: "Kanban", category: "App" } },
          is_featured: true,
        },
      ],
      total: 1,
    });
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(
      screen.getByRole("tab", { name: /appCenter.officialApps/ }),
    );

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/apps?view=official",
    );
    expect(await screen.findByText("Agent Kanban")).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByText("alpha-app")).not.toBeInTheDocument();
  });

  it("shows the official view when visiting /apps?view=official directly", async () => {
    renderPage(["/apps?view=official"]);

    expect(
      await screen.findByLabelText("appCenter.searchOfficial"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("appCenter.officialAppsEmpty"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
  });

  it("falls back to installed apps for unknown view values", async () => {
    renderPage(["/apps?view=bogus"]);

    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).not.toHaveBeenCalled();
  });

  it("enters the market view via ?view=market and mounts the market lazily", async () => {
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByRole("tab", { name: /appCenter.appMarket/ }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/apps?view=market",
    );
    expect(
      await screen.findByLabelText("appCenter.searchMarket"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByText("alpha-app")).not.toBeInTheDocument();
  });

  it("shows the market when visiting /apps?view=market directly", async () => {
    renderPage(["/apps?view=market"]);

    expect(
      await screen.findByLabelText("appCenter.searchMarket"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
  });

  it("returns to installed apps and preserves unrelated query params", async () => {
    renderPage(["/apps?foo=1"]);
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByRole("tab", { name: /appCenter.appMarket/ }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/apps?foo=1&view=market",
    );

    fireEvent.click(screen.getByRole("tab", { name: /appCenter.myApps/ }));
    expect(screen.getByTestId("location")).toHaveTextContent(/\/apps\?foo=1$/);
    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
  });

  it("offers official and market entry points when no apps are installed", async () => {
    hoisted.listApps.mockResolvedValue({ apps: [], total: 0 });
    renderPage();

    const goToOfficial = await screen.findByRole("button", {
      name: /appCenter.browseOfficialApps/,
    });
    expect(
      screen.getByRole("button", { name: /appCenter.browseMarket/ }),
    ).toBeInTheDocument();

    fireEvent.click(goToOfficial);

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/apps?view=official",
    );
    expect(
      await screen.findByText("appCenter.officialAppsEmpty"),
    ).toBeInTheDocument();
  });

  it("filters installed apps by search and offers to clear filters", async () => {
    renderPage();
    await screen.findByText("alpha-app");

    const searchInput = screen.getByLabelText("appCenter.search");
    fireEvent.change(searchInput, { target: { value: "alpha" } });

    expect(screen.getByText("alpha-app")).toBeInTheDocument();
    expect(screen.queryByText("beta-app")).not.toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: "no-such-app" } });
    expect(screen.queryByText("alpha-app")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /appCenter.clearFilters/ }),
    );
    expect(screen.getByText("alpha-app")).toBeInTheDocument();
    expect(screen.getByText("beta-app")).toBeInTheDocument();
  });

  it("recovers from a load failure via the retry button", async () => {
    hoisted.listApps
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ apps: [makeApp("alpha-app")], total: 1 });
    renderPage();

    const retryBtn = await screen.findByRole("button", {
      name: /common.retry/,
    });
    fireEvent.click(retryBtn);

    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
  });

  it("opens an installed app in the embedded view on card click", async () => {
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByText("alpha-app"));

    // No route component is registered in this test, so the embedded view
    // shows its not-loaded placeholder — proving the embed flow was entered.
    expect(
      await screen.findByText("appCenter.appNotLoaded"),
    ).toBeInTheDocument();
  });

  it("restores an OS PawApp when navigating back and forward", async () => {
    window.history.replaceState({ osApp: "core.app-center" }, "", "/os");
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByText("alpha-app"));

    expect(window.location.pathname).toBe("/os");
    expect(window.history.state).toEqual({
      osApp: "core.app-center",
      osPawAppId: "alpha-app",
    });
    expect(
      await screen.findByText("appCenter.appNotLoaded"),
    ).toBeInTheDocument();

    window.history.back();
    await waitFor(() => {
      expect(screen.getByText("alpha-app")).toBeInTheDocument();
    });

    window.history.forward();
    expect(
      await screen.findByText("appCenter.appNotLoaded"),
    ).toBeInTheDocument();
  });
});
