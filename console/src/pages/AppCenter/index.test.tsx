// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Modal } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation } from "react-router-dom";

import { renderWithProviders } from "@/test/common_setup";
import AppCenterPage from "./index";

const hoisted = vi.hoisted(() => ({
  listApps: vi.fn(),
  uninstall: vi.fn(),
  fetchMarketPlugins: vi.fn(),
  installPlugin: vi.fn(),
  loadPawApp: vi.fn(),
  routeSnapshot: vi.fn(),
  removePluginAppState: vi.fn(),
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
  useRoutes: () => hoisted.routeSnapshot(),
}));

vi.mock("@/plugins/usePluginLoader", () => ({
  loadPawApp: hoisted.loadPawApp,
}));

vi.mock("@/os/osCleanup", () => ({
  removePluginAppState: hoisted.removePluginAppState,
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

function makeMarketApp(id: string) {
  return {
    id,
    display_name: id,
    developer: "dev",
    owner: "dev",
    version: "1.0.0",
    logo_url: null,
    downloads: 1,
    view_count: 1,
    details_url: null,
    locales: { en: { description: id, category: "app" } },
    is_featured: false,
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
    hoisted.loadPawApp.mockReset();
    hoisted.routeSnapshot.mockReset();
    hoisted.removePluginAppState.mockReset();
    hoisted.routeSnapshot.mockReturnValue([]);
    hoisted.loadPawApp.mockResolvedValue(undefined);
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

  it("loads a newly installed market app without reloading", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeMarketApp("new-app")],
      total: 1,
    });
    hoisted.installPlugin.mockResolvedValue({
      id: "new-app",
      name: "New App",
    });
    renderPage(["/apps?view=market"]);

    fireEvent.click(await screen.findByText("appCenter.install"));

    await waitFor(() =>
      expect(hoisted.loadPawApp).toHaveBeenCalledWith("new-app"),
    );
  });

  it("does not load an old bundle when updating an installed market app", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeMarketApp("alpha-app")],
      total: 1,
    });
    hoisted.installPlugin.mockResolvedValue({
      id: "alpha-app",
      name: "Alpha App",
    });
    renderPage(["/apps?view=market"]);
    await waitFor(() => expect(hoisted.listApps).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByText("appCenter.install"));

    await waitFor(() => expect(hoisted.installPlugin).toHaveBeenCalledTimes(1));
    expect(hoisted.loadPawApp).not.toHaveBeenCalled();
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

  it("loads an installed app on demand on card click", async () => {
    const AppPage = () => <div>Loaded PawApp</div>;
    hoisted.loadPawApp.mockImplementationOnce(async () => {
      hoisted.routeSnapshot.mockReturnValue([
        {
          id: "alpha.page",
          path: "/apps/alpha-app",
          source: "alpha-app",
          Component: AppPage,
        },
      ]);
    });
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByText("alpha-app"));

    await waitFor(() =>
      expect(hoisted.loadPawApp).toHaveBeenCalledWith(
        "alpha-app",
        "/apps/alpha-app",
      ),
    );
    expect(await screen.findByText("Loaded PawApp")).toBeInTheDocument();
  });

  it("cleans the loaded PawApp runtime after uninstall", async () => {
    hoisted.uninstall.mockResolvedValue(undefined);
    hoisted.listApps
      .mockResolvedValueOnce({ apps: [makeApp("alpha-app")], total: 1 })
      .mockResolvedValueOnce({ apps: [], total: 0 });
    vi.spyOn(Modal, "confirm").mockImplementation((options) => {
      void options.onOk?.();
      return { destroy: vi.fn(), update: vi.fn() };
    });
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(
      screen.getByRole("button", { name: /appCenter.moreActions/ }),
    );
    fireEvent.click(await screen.findByText("appCenter.uninstall"));

    await waitFor(() =>
      expect(hoisted.uninstall).toHaveBeenCalledWith("alpha-app"),
    );
    expect(hoisted.removePluginAppState).toHaveBeenCalledWith("alpha-app");
  });

  it("restores an OS PawApp when navigating back and forward", async () => {
    hoisted.routeSnapshot.mockReturnValue([
      {
        id: "alpha.page",
        path: "/apps/alpha-app",
        source: "alpha-app",
        Component: () => <div>Loaded PawApp</div>,
      },
    ]);
    window.history.replaceState({ osApp: "core.app-center" }, "", "/os");
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByText("alpha-app"));

    await waitFor(() =>
      expect(window.history.state).toEqual({
        osApp: "core.app-center",
        osPawAppId: "alpha-app",
      }),
    );
    expect(window.location.pathname).toBe("/os");
    expect(await screen.findByText("Loaded PawApp")).toBeInTheDocument();

    window.history.back();
    await waitFor(() => {
      expect(screen.getByText("alpha-app")).toBeInTheDocument();
    });

    window.history.forward();
    expect(await screen.findByText("Loaded PawApp")).toBeInTheDocument();
  });
});
