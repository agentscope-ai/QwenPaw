/**
 * Unit tests for PluginManagerPage, the three-tab plugin manager shell.
 *
 * Facts that shaped this suite (each one read off the source or measured):
 *
 * 1. The page owns exactly three things: which tab the `view` search param
 *    selects, what it writes back to the URL when a tab is clicked, and the
 *    `handleInstalled` callback (reload the frontend plugin, then refresh,
 *    even if the reload throws). Everything else lives in children that have
 *    suites next door (`InstalledPluginList`, `OfficialPluginList`,
 *    `MarketPluginList`, `InstallPluginModal`, `usePluginManager`,
 *    `useInstallModal`, `MarketplaceHeader`), so those are stubbed on purpose
 *    and every assertion is about this file's wiring.
 * 2. `useSearchParams` runs for real under a `MemoryRouter` (via
 *    `renderWithProviders`), and a location probe renders the live search
 *    string, so the URL contract is asserted on the real router state instead
 *    of on mock call args.
 * 3. Tab selection is `viewParam === "official" || viewParam === "market" ?
 *    viewParam : "installed"`, so any other value (including none) lands on
 *    "installed". Both whitelist members and the fallback are asserted.
 * 4. Tab change writes `view=<key>` for official/market and DELETES the param
 *    for installed, with `{ replace: true }`. The probe asserts the resulting
 *    search string after each click.
 * 5. antd Tabs render for real, so `aria-selected` on the tab nodes is the
 *    genuine article. Inactive panes stay mounted but display-hidden after
 *    being visited, so pane visibility (not mere presence) is what tells the
 *    active tab apart.
 * 6. `updates.size > 0` renders an antd Badge with the count inside the
 *    installed tab label; `updates` is a `Map`, so the stub hands the page a
 *    real Map.
 * 7. `handleInstalled` is passed to `useInstallModal` and also to the official
 *    and market lists as `onInstalled`. The install-modal stub captures the
 *    callback it receives so the "reload then refresh" and "refresh even when
 *    reload fails" contracts can be driven from inside the page.
 * 8. `MarketPluginList` receives `installedPlugins={plugins ?? []}`, so a null
 *    plugin list must arrive at the child as an empty array.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import React from "react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import type { InstallPluginResult, PluginInfo } from "@/api/modules/plugin";

const env = vi.hoisted(() => ({
  plugins: null as PluginInfo[] | null,
  loading: false,
  refresh: vi.fn(),
  refreshUpdates: vi.fn(),
  uninstallingId: null as string | null,
  handleUninstall: vi.fn(),
  updates: new Map<string, { version: string; source: string; name: string }>(),
  updatesLoading: false,
  updatingId: null as string | null,
  updatingAll: false,
  updateOne: vi.fn(),
  updateAll: vi.fn(),
  installOpen: false,
  openModal: vi.fn(),
  closeModal: vi.fn(),
  capturedOnSuccess: null as
    | null
    | ((result: InstallPluginResult) => void | Promise<void>),
  reloadFrontendPlugin: vi.fn(),
}));

// Stable i18n instance (see the Backups page suite for why stability matters).
const i18nStub = vi.hoisted(() => {
  const t = (key: string) => key;
  const i18n = {
    resolvedLanguage: "en",
    changeLanguage: () => undefined,
    language: "en",
  };
  return { t, i18n };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: i18nStub.t, i18n: i18nStub.i18n }),
}));

vi.mock("./hooks/usePluginManager", () => ({
  usePluginManager: () => ({
    plugins: env.plugins,
    loading: env.loading,
    refresh: env.refresh,
    refreshUpdates: env.refreshUpdates,
    uninstallingId: env.uninstallingId,
    handleUninstall: env.handleUninstall,
    updates: env.updates,
    updatesLoading: env.updatesLoading,
    updatingId: env.updatingId,
    updatingAll: env.updatingAll,
    updateOne: env.updateOne,
    updateAll: env.updateAll,
  }),
}));

vi.mock("./hooks/useInstallModal", () => ({
  useInstallModal: (
    onSuccess: (result: InstallPluginResult) => void | Promise<void>,
  ) => {
    env.capturedOnSuccess = onSuccess;
    return {
      installOpen: env.installOpen,
      openModal: env.openModal,
      closeModal: env.closeModal,
      localInstalling: false,
      urlInstalling: false,
      localSel: null,
      clearSelection: vi.fn(),
      dragOver: false,
      form: {},
      fileInputRef: { current: null },
      browseZip: vi.fn(),
      handleZipPicked: vi.fn(),
      handleDragOver: vi.fn(),
      handleDragLeave: vi.fn(),
      handleDrop: vi.fn(),
      handleInstallLocal: vi.fn(),
      handleInstallUrl: vi.fn(),
    };
  },
}));

vi.mock("@/pages/Market/components/MarketplaceHeader", () => ({
  MarketplaceHeader: (props: {
    activeSection: string;
    extra?: React.ReactNode;
  }) => (
    <div data-testid="market-header" data-section={props.activeSection}>
      {props.extra}
    </div>
  ),
}));

vi.mock("@/plugins/usePluginLoader", () => ({
  reloadFrontendPlugin: env.reloadFrontendPlugin,
}));

vi.mock("./components/InstallPluginModal", () => ({
  InstallPluginModal: (props: { installOpen?: boolean }) => (
    <div
      data-testid="install-modal"
      data-open={String(props.installOpen === true)}
    />
  ),
}));

vi.mock("./components/InstalledPluginList", () => ({
  InstalledPluginList: (props: {
    plugins: PluginInfo[] | null;
    loading: boolean;
    uninstallingId: string | null;
    onRefresh: () => void;
    onUninstall: (id: string) => void;
    updates: Map<string, unknown>;
    updatesLoading: boolean;
    updatingId: string | null;
    updatingAll: boolean;
    onUpdate: (id: string) => void;
    onUpdateAll: () => void;
  }) => (
    <div
      data-testid="installed-pane"
      data-plugins={props.plugins === null ? "null" : props.plugins.length}
      data-loading={String(props.loading)}
      data-uninstalling-id={String(props.uninstallingId)}
      data-updates={props.updates.size}
      data-updates-loading={String(props.updatesLoading)}
      data-updating-id={String(props.updatingId)}
      data-updating-all={String(props.updatingAll)}
    >
      <button onClick={() => props.onRefresh()}>pane-refresh</button>
      <button onClick={() => props.onUninstall("p9")}>pane-uninstall</button>
      <button onClick={() => props.onUpdate("p8")}>pane-update-one</button>
      <button onClick={() => props.onUpdateAll()}>pane-update-all</button>
    </div>
  ),
}));

vi.mock("./components/OfficialPluginList", () => ({
  OfficialPluginList: (props: {
    onInstalled: (result: InstallPluginResult) => void;
  }) => (
    <div data-testid="official-pane">
      <button
        onClick={() =>
          props.onInstalled({
            id: "p-official",
            name: "Official",
          } as InstallPluginResult)
        }
      >
        official-installed
      </button>
    </div>
  ),
}));

vi.mock("./components/MarketPluginList", () => ({
  MarketPluginList: (props: {
    onInstalled: (result: InstallPluginResult) => void;
    installedPlugins: PluginInfo[];
  }) => (
    <div
      data-testid="market-pane"
      data-installed-count={props.installedPlugins.length}
    >
      <button
        onClick={() =>
          props.onInstalled({
            id: "p-market",
            name: "Market",
          } as InstallPluginResult)
        }
      >
        market-installed
      </button>
    </div>
  ),
}));

import PluginManagerPage from "./index";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="probe-search">{location.search}</div>;
}

function renderPage(initialEntry = "/market?tab=plugins") {
  return renderWithProviders(
    <>
      <PluginManagerPage />
      <LocationProbe />
    </>,
    { initialEntries: [initialEntry] },
  );
}

function makePlugin(id: string): PluginInfo {
  return {
    id,
    name: `Plugin ${id}`,
    version: "1.0.0",
    description: `Desc ${id}`,
    author: "tester",
    loaded: true,
  } as PluginInfo;
}

function installedTab() {
  return screen.getByRole("tab", { name: /pluginManager\.installed/ });
}

describe("PluginManagerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    env.plugins = [makePlugin("p1"), makePlugin("p2")];
    env.loading = false;
    env.uninstallingId = null;
    env.updates = new Map();
    env.updatesLoading = false;
    env.updatingId = null;
    env.updatingAll = false;
    env.installOpen = false;
    env.capturedOnSuccess = null;
    env.reloadFrontendPlugin.mockResolvedValue(true);
    env.refresh.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
  });

  it("selects the installed tab when no view param is present", () => {
    renderPage();

    expect(installedTab()).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tab", { name: "pluginManager.officialTitle" }),
    ).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("installed-pane")).toBeVisible();
  });

  it("selects the official tab from the view param", () => {
    renderPage("/market?tab=plugins&view=official");

    expect(
      screen.getByRole("tab", { name: "pluginManager.officialTitle" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(installedTab()).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("official-pane")).toBeVisible();
  });

  it("selects the market tab from the view param", () => {
    renderPage("/market?tab=plugins&view=market");

    expect(
      screen.getByRole("tab", { name: "pluginManager.marketTitle" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("market-pane")).toBeVisible();
  });

  it("falls back to the installed tab for an unknown view param", () => {
    renderPage("/market?tab=plugins&view=bogus");

    expect(installedTab()).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("installed-pane")).toBeVisible();
  });

  it("keeps other search params untouched while switching tabs", () => {
    renderPage("/market?tab=plugins");

    fireEvent.click(
      screen.getByRole("tab", { name: "pluginManager.marketTitle" }),
    );
    expect(screen.getByTestId("probe-search").textContent).toBe(
      "?tab=plugins&view=market",
    );

    fireEvent.click(
      screen.getByRole("tab", { name: "pluginManager.officialTitle" }),
    );
    expect(screen.getByTestId("probe-search").textContent).toBe(
      "?tab=plugins&view=official",
    );

    fireEvent.click(installedTab());
    // The installed tab deletes the view param instead of setting it.
    expect(screen.getByTestId("probe-search").textContent).toBe("?tab=plugins");
  });

  it("shows the update badge count inside the installed tab label", () => {
    env.updates = new Map([
      ["p1", { version: "2.0.0", source: "s1", name: "Plugin p1" }],
      ["p2", { version: "3.1.0", source: "s2", name: "Plugin p2" }],
    ]);

    renderPage();

    expect(installedTab().textContent).toContain("2");
  });

  it("shows no badge when there is nothing to update", () => {
    env.updates = new Map();

    renderPage();

    const tab = installedTab();
    expect(tab.textContent).toBe("pluginManager.installed");
  });

  it("passes the manager state down to the installed pane", () => {
    env.loading = true;
    env.uninstallingId = "p1";
    env.updatesLoading = true;
    env.updatingId = "p2";
    env.updatingAll = true;
    env.updates = new Map([
      ["p1", { version: "2.0.0", source: "s1", name: "Plugin p1" }],
    ]);

    renderPage();

    const pane = screen.getByTestId("installed-pane");
    expect(pane).toHaveAttribute("data-plugins", "2");
    expect(pane).toHaveAttribute("data-loading", "true");
    expect(pane).toHaveAttribute("data-uninstalling-id", "p1");
    expect(pane).toHaveAttribute("data-updates", "1");
    expect(pane).toHaveAttribute("data-updates-loading", "true");
    expect(pane).toHaveAttribute("data-updating-id", "p2");
    expect(pane).toHaveAttribute("data-updating-all", "true");
  });

  it("routes the installed pane callbacks to the manager hook", () => {
    renderPage();

    fireEvent.click(screen.getByText("pane-refresh"));
    expect(env.refreshUpdates).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("pane-uninstall"));
    expect(env.handleUninstall).toHaveBeenCalledWith("p9");
    fireEvent.click(screen.getByText("pane-update-one"));
    expect(env.updateOne).toHaveBeenCalledWith("p8");
    fireEvent.click(screen.getByText("pane-update-all"));
    expect(env.updateAll).toHaveBeenCalledTimes(1);
  });

  it("hands the null plugin list to the market pane as an empty array", () => {
    env.plugins = null;

    renderPage("/market?tab=plugins&view=market");

    expect(screen.getByTestId("market-pane")).toHaveAttribute(
      "data-installed-count",
      "0",
    );
  });

  it("hands the real plugin list to the market pane", () => {
    renderPage("/market?tab=plugins&view=market");

    expect(screen.getByTestId("market-pane")).toHaveAttribute(
      "data-installed-count",
      "2",
    );
  });

  it("opens the publish page in a new tab from the header button", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "pluginManager.publishBtn" }),
    );
    expect(openSpy).toHaveBeenCalledWith(
      "https://platform.agentscope.io/plugins",
      "_blank",
    );

    openSpy.mockRestore();
  });

  it("opens the install modal from the header button", () => {
    renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "pluginManager.installBtn" }),
    );
    expect(env.openModal).toHaveBeenCalledTimes(1);
  });

  it("mirrors the install modal open flag into the modal component", () => {
    env.installOpen = true;

    renderPage();

    expect(screen.getByTestId("install-modal")).toHaveAttribute(
      "data-open",
      "true",
    );
  });

  it("marks the marketplace header as the plugins section", () => {
    renderPage();

    expect(screen.getByTestId("market-header")).toHaveAttribute(
      "data-section",
      "plugins",
    );
  });

  it("reloads the frontend plugin then refreshes after an install", async () => {
    renderPage();

    const onSuccess = env.capturedOnSuccess;
    expect(typeof onSuccess).toBe("function");
    await onSuccess!({ id: "p-new", name: "New" } as InstallPluginResult);

    expect(env.reloadFrontendPlugin).toHaveBeenCalledWith("p-new");
    expect(env.refresh).toHaveBeenCalledTimes(1);
    expect(env.reloadFrontendPlugin.mock.invocationCallOrder[0]).toBeLessThan(
      env.refresh.mock.invocationCallOrder[0],
    );
  });

  it("still refreshes when the frontend reload fails", async () => {
    env.reloadFrontendPlugin.mockRejectedValue(new Error("loader down"));
    renderPage();

    // The handler is typed `void | Promise<void>`, so normalise to a promise
    // before swallowing the loader rejection the handler deliberately rethrows.
    await Promise.resolve(
      env.capturedOnSuccess!({
        id: "p-bad",
        name: "Bad",
      } as InstallPluginResult),
    ).catch(() => undefined);

    // The refresh runs in a `finally`, so the failure above must not skip it.
    expect(env.refresh).toHaveBeenCalledTimes(1);
  });

  it("uses the same installed handler for official installs", () => {
    renderPage("/market?tab=plugins&view=official");

    fireEvent.click(screen.getByText("official-installed"));
    expect(env.reloadFrontendPlugin).toHaveBeenCalledWith("p-official");
  });

  it("uses the same installed handler for market installs", () => {
    renderPage("/market?tab=plugins&view=market");

    fireEvent.click(screen.getByText("market-installed"));
    expect(env.reloadFrontendPlugin).toHaveBeenCalledWith("p-market");
  });

  it("keeps the install modal in the tree even when closed", () => {
    env.installOpen = false;

    renderPage();

    expect(screen.getByTestId("install-modal")).toBeInTheDocument();
    expect(screen.getByTestId("install-modal")).toHaveAttribute(
      "data-open",
      "false",
    );
  });

  it("does not render the installed pane content before it is visited", () => {
    renderPage("/market?tab=plugins&view=market");

    // rc-tabs mounts a pane lazily: an unvisited pane is not in the DOM yet.
    expect(screen.queryByTestId("installed-pane")).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("market-pane")).getByText("market-installed"),
    ).toBeInTheDocument();
  });
});
