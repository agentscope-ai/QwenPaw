vi.mock("../../plugins/pawapp-sdk/browserSession", () => ({
  prepareBrowserSession: vi.fn().mockResolvedValue(null),
}));
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
  reloadPawApp: vi.fn(),
  routeSnapshot: vi.fn(),
  removePluginAppState: vi.fn(),
  warning: vi.fn(),
  uploadPlugin: vi.fn(),
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
  // Transparent to `extra`: MarketplaceHeader forwards the page header
  // actions (install button) through it.
  PageHeader: ({
    current,
    extra,
  }: {
    current: string;
    extra?: import("react").ReactNode;
  }) => (
    <div>
      {current}
      {extra}
    </div>
  ),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      loading: vi.fn(),
      success: vi.fn(),
      error: vi.fn(),
      warning: hoisted.warning,
    },
  }),
}));

vi.mock("antd", async () => {
  const actual = await vi.importActual<typeof import("antd")>("antd");
  // rc-dialog defers children until an open animation that never runs in
  // jsdom; render the install dialog synchronously so the URL-install flow
  // below can drive its real Form + Input.
  const ReactModule = await import("react");
  const ModalStub = Object.assign(
    (props: { open?: boolean; title?: unknown; children?: unknown }) => {
      if (!props.open) return null;
      return ReactModule.createElement(
        "div",
        { role: "dialog" },
        ReactModule.createElement(
          "div",
          { "data-testid": "modal-title" },
          props.title as never,
        ),
        props.children as never,
      );
    },
    { confirm: vi.fn(), info: vi.fn() },
  );
  return { ...actual, Modal: ModalStub };
});

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
  reloadPawApp: hoisted.reloadPawApp,
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
  uploadPlugin: hoisted.uploadPlugin,
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

function makeMarketApp(id: string, overrides: Record<string, unknown> = {}) {
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
    ...overrides,
  };
}

function renderPage(initialEntries: string[] = ["/market"]) {
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
    hoisted.reloadPawApp.mockReset();
    hoisted.routeSnapshot.mockReset();
    hoisted.removePluginAppState.mockReset();
    hoisted.warning.mockReset();
    hoisted.uploadPlugin.mockReset();
    hoisted.routeSnapshot.mockReturnValue([]);
    hoisted.loadPawApp.mockResolvedValue(undefined);
    hoisted.reloadPawApp.mockResolvedValue(undefined);
    hoisted.listApps.mockResolvedValue({
      apps: [makeApp("alpha-app"), makeApp("beta-app", { category: "games" })],
      total: 2,
    });
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
    window.history.replaceState({}, "", "/market");
  });

  it("opens the app-flavoured install modal from the header button", async () => {
    renderPage();
    expect(await screen.findByText("alpha-app")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "appCenter.installApp" }),
    );

    expect(
      await screen.findByText("appCenter.installAppTitle"),
    ).toBeInTheDocument();
    expect(screen.getByText("appCenter.installAppHint")).toBeInTheDocument();
  });

  it("loads a URL-installed package that resolves to a PawApp", async () => {
    hoisted.installPlugin.mockResolvedValue({
      id: "gamma-app",
      name: "gamma",
    });
    hoisted.listApps
      .mockResolvedValueOnce({ apps: [makeApp("alpha-app")], total: 1 })
      .mockResolvedValue({
        apps: [makeApp("alpha-app"), makeApp("gamma-app")],
        total: 2,
      });
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", { name: "appCenter.installApp" }),
    );
    fireEvent.change(
      screen.getByPlaceholderText("pluginManager.urlPlaceholder"),
      { target: { value: "https://x/gamma.zip" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pluginManager.installFromUrl" }),
    );

    await waitFor(() =>
      expect(hoisted.installPlugin).toHaveBeenCalledWith("https://x/gamma.zip"),
    );
    await waitFor(() =>
      expect(hoisted.loadPawApp).toHaveBeenCalledWith("gamma-app"),
    );
    expect(hoisted.warning).not.toHaveBeenCalled();
    // Apps stay put on the App Center page.
    expect(screen.getByTestId("location").textContent).toBe("/market");
  });

  it("warns and jumps to the plugins tab when the installed package is not an app", async () => {
    hoisted.installPlugin.mockResolvedValue({
      id: "plain-plugin",
      name: "plain",
    });
    hoisted.listApps.mockResolvedValue({
      apps: [makeApp("alpha-app")],
      total: 1,
    });
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", { name: "appCenter.installApp" }),
    );
    fireEvent.change(
      screen.getByPlaceholderText("pluginManager.urlPlaceholder"),
      { target: { value: "https://x/plain.zip" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pluginManager.installFromUrl" }),
    );

    await waitFor(() => expect(hoisted.warning).toHaveBeenCalledTimes(1));
    expect(hoisted.loadPawApp).not.toHaveBeenCalled();
    expect(hoisted.reloadPawApp).not.toHaveBeenCalled();
    // Plain plugins land on the Plugins tab (installed sub-tab default).
    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toBe(
        "/market?tab=plugins",
      ),
    );
  });

  it("renders installed apps by default without mounting external views", async () => {
    renderPage();

    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
    expect(screen.getByText("beta-app")).toBeInTheDocument();

    // The market view must not load on the default tab.
    expect(
      screen.queryByLabelText("appCenter.searchMarket"),
    ).not.toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).not.toHaveBeenCalled();
  });

  it("shows the official view when visiting it directly", async () => {
    renderPage(["/market?view=official"]);

    expect(
      await screen.findByLabelText("appCenter.searchOfficial"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
    expect(hoisted.fetchMarketPlugins.mock.calls[0][0]).toEqual(
      expect.objectContaining({ is_featured: true, page_number: 1 }),
    );
  });

  it("falls back to installed apps for unknown view values", async () => {
    renderPage(["/market?view=bogus"]);

    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
    expect(hoisted.fetchMarketPlugins).not.toHaveBeenCalled();
  });

  it("enters the market view via ?view=market and mounts the market lazily", async () => {
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByRole("tab", { name: /appCenter.appMarket/ }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/market?view=market",
    );
    expect(
      await screen.findByLabelText("appCenter.searchMarket"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
    expect(screen.queryByText("alpha-app")).not.toBeInTheDocument();
  });

  it("shows the market when visiting /market?view=market directly", async () => {
    renderPage(["/market?view=market"]);

    expect(
      await screen.findByLabelText("appCenter.searchMarket"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1),
    );
  });

  it("marks an installed app as installed in the market", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeMarketApp("alpha-app")],
      total: 1,
    });
    renderPage(["/market?view=market"]);

    expect(
      await screen.findByRole("button", {
        name: "appCenter.installedStatus",
      }),
    ).toBeDisabled();
    expect(screen.queryByText("appCenter.install")).not.toBeInTheDocument();
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
    renderPage(["/market?view=market"]);

    fireEvent.click(await screen.findByText("appCenter.install"));

    await waitFor(() =>
      expect(hoisted.loadPawApp).toHaveBeenCalledWith("new-app"),
    );
  });

  it("does not reinstall an installed market app at the same version", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeMarketApp("alpha-app")],
      total: 1,
    });
    renderPage(["/market?view=market"]);
    await waitFor(() => expect(hoisted.listApps).toHaveBeenCalledTimes(1));

    const installedButton = await screen.findByRole("button", {
      name: "appCenter.installedStatus",
    });
    expect(installedButton).toBeDisabled();
    fireEvent.click(installedButton);
    expect(hoisted.installPlugin).not.toHaveBeenCalled();
    expect(hoisted.loadPawApp).not.toHaveBeenCalled();
  });

  it("offers an update for an installed market app with a newer version", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({
      plugins: [makeMarketApp("alpha-app", { version: "2.0.0" })],
      total: 1,
    });
    hoisted.installPlugin.mockResolvedValue({
      id: "alpha-app",
      name: "Alpha App",
    });
    renderPage(["/market?view=market"]);
    await waitFor(() => expect(hoisted.listApps).toHaveBeenCalledTimes(1));

    const updateButton = await screen.findByRole("button", {
      name: "appCenter.update",
    });
    expect(updateButton).toBeEnabled();
    fireEvent.click(updateButton);
    await waitFor(() => expect(hoisted.installPlugin).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(hoisted.reloadPawApp).toHaveBeenCalledWith("alpha-app"),
    );
    expect(hoisted.listApps).toHaveBeenCalledTimes(2);
  });

  it("returns to installed apps and preserves unrelated query params", async () => {
    renderPage(["/market?foo=1"]);
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByRole("tab", { name: /appCenter.appMarket/ }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/market?foo=1&view=market",
    );

    fireEvent.click(screen.getByRole("tab", { name: /appCenter.myApps/ }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      /\/market\?foo=1$/,
    );
    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
  });

  it("offers official apps and the app market when no apps are installed", async () => {
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
      "/market?view=official",
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

  it("returns to the previous non-OS history entry when closing an app", async () => {
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
    window.history.replaceState({}, "", "/chat");
    window.history.pushState({}, "", "/market");
    renderPage();
    await screen.findByText("alpha-app");

    fireEvent.click(screen.getByText("alpha-app"));

    expect(await screen.findByText("Loaded PawApp")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/apps/alpha-app");
    expect(window.history.state).toEqual({ pawappInline: true });

    fireEvent.click(screen.getByTitle("appCenter.backToListHint"));

    await waitFor(() => expect(window.location.pathname).toBe("/market"));
    expect(await screen.findByText("alpha-app")).toBeInTheDocument();
    expect(window.history.state).toEqual({});

    window.history.back();
    await waitFor(() => expect(window.location.pathname).toBe("/chat"));
    expect(screen.queryByText("Loaded PawApp")).not.toBeInTheDocument();
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
      screen.getByRole("button", { name: "appCenter.moreActions" }),
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /appCenter.uninstall/ }),
    );

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
