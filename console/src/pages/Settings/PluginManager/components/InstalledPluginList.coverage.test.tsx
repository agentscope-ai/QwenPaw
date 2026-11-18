/**
 * Unit tests for InstalledPluginList, the installed-plugins pane of the plugin
 * manager page.
 *
 * Facts that shaped this suite (each one read off the source or measured):
 *
 * 1. antd renders for real here (`Alert, Badge, Button, Empty, Input, Spin,
 *    Table, Tag, Typography` all come straight from `antd`), so the search box,
 *    the two empty-state descriptions, the status tags and the update badge are
 *    the genuine article and are queried by role/label/text. No class names are
 *    asserted: the CSS-module class names are hashed.
 * 2. `@/hooks/useIsMobile` and `../hooks/usePluginColumns` are mocked. The
 *    columns hook has its own suite next door, so rendering the real one here
 *    would mix two files' coverage into one run. The mobile hook is mocked
 *    because it reads `window.matchMedia`, and both branches of this component
 *    (`isMobile || viewMode === "card"`) need to be reachable deterministically.
 * 3. `./PluginViewToggle` and `./PluginTypeTag` are rendered for real. The
 *    toggle is what switches `viewMode`, so stubbing it would make the table
 *    branch unreachable; it sits on top of the shared `@agentscope-ai/design`
 *    Tabs stub, which renders one `role="tab"` button per item in source order
 *    ("list" first, then "card").
 * 4. Card markup uses `<article aria-label={plugin.name}>`, so "which branch is
 *    on screen" is asserted by counting articles rather than by inspecting DOM
 *    nesting. The list branch renders no article at all.
 * 5. Both empty-state descriptions are reachable and differ: `noPlugins` when
 *    the plugin list is empty, `noMatchingPlugins` when a search filtered
 *    everything out. That distinction is a user-visible contract, so both are
 *    asserted.
 * 6. Update availability is per plugin: `updates.get(plugin.id)`. An absent
 *    entry renders no update button at all (not a disabled one), which is what
 *    the "no update for this plugin" case asserts.
 * 7. The disable rules are cross-plugin, and are asserted as written in the
 *    source: an update button is disabled when a full update run is in flight,
 *    or when a *different* plugin is updating; an uninstall button is disabled
 *    only when a different plugin is uninstalling.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import React from "react";
import type { PluginInfo, PluginUpdateInfo } from "@/api/modules/plugin";

const env = vi.hoisted(() => ({
  isMobile: false,
  columns: [] as unknown[],
}));

vi.mock("react-i18next", () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts ? `${key}:${JSON.stringify(opts)}` : key;
  return {
    useTranslation: () => ({
      t,
      i18n: { resolvedLanguage: "en", changeLanguage: vi.fn(), language: "en" },
    }),
  };
});

vi.mock("@/hooks/useIsMobile", () => ({
  useIsMobile: () => env.isMobile,
}));

vi.mock("../hooks/usePluginColumns", () => ({
  // Test double on purpose (see note 2): a minimal column set that renders the
  // plugin name, so the table branch can be asserted without pulling the real
  // hook's coverage into this run.
  usePluginColumns: () => env.columns,
}));

// The real ./PluginTypeTag is rendered (see note 3), and it builds its whole
// type map at module scope, including `<SparkWifiLine />` from
// @agentscope-ai/icons. The shared icons stub does not export that name, so
// without a local mock the module evaluates `jsx(undefined)` and React warns.
// This is the same local-mock approach the neighbouring PluginTypeTag and
// usePluginColumns suites already use; the shared stub is deliberately left
// untouched.
vi.mock("@agentscope-ai/icons", () => ({
  SparkWifiLine: (props: Record<string, unknown>) => (
    <span data-icon="SparkWifiLine" {...props} />
  ),
}));

import { InstalledPluginList } from "./InstalledPluginList";

function makePlugin(
  id: string,
  overrides: Partial<PluginInfo> = {},
): PluginInfo {
  return {
    id,
    name: `Plugin ${id}`,
    version: `1.${id}.0`,
    description: `Description for ${id}`,
    author: `Author ${id}`,
    enabled: true,
    loaded: true,
    plugin_type: "tool",
    ...overrides,
  } as PluginInfo;
}

function makeUpdate(version: string): PluginUpdateInfo {
  return { version, source: "market", name: "upstream" } as PluginUpdateInfo;
}

const TWO_PLUGINS = [
  makePlugin("one"),
  makePlugin("two", { loaded: false, description: "", author: undefined }),
];

function renderList(
  opts: Partial<React.ComponentProps<typeof InstalledPluginList>> = {},
) {
  const props = {
    plugins: TWO_PLUGINS,
    loading: false,
    uninstallingId: null,
    onRefresh: vi.fn(),
    onUninstall: vi.fn(),
    updates: new Map<string, PluginUpdateInfo>(),
    updatesLoading: false,
    updatingId: null,
    updatingAll: false,
    onUpdate: vi.fn(),
    onUpdateAll: vi.fn(),
    ...opts,
  } as React.ComponentProps<typeof InstalledPluginList>;
  render(<InstalledPluginList {...props} />);
  return props;
}

function searchBox(): HTMLInputElement {
  return screen.getByPlaceholderText("pluginManager.filterByName");
}

function articles(): HTMLElement[] {
  return screen.queryAllByRole("article");
}

/** The view toggle renders one tab per mode, "list" first (see note 3). */
function switchToListView() {
  const tabs = screen.getAllByRole("tab");
  expect(tabs).toHaveLength(2);
  fireEvent.click(tabs[0]);
}

/**
 * The uninstall buttons of the list (catalog-row) branch, in plugin order.
 *
 * Those rows live in a container the stylesheet hides at desktop widths (the
 * `mobileTableList` class only shows it through a media query, which jsdom does
 * not evaluate), and `getByRole` skips hidden nodes by default. A probe measured
 * this: in list view the DOM holds 5 `<button>` elements while a role query
 * finds only 1. The text query does not filter on visibility, so the labels are
 * looked up by text and walked up to their own button. These are the buttons a
 * narrow-window user taps, and their click contract is asserted here.
 */
function catalogUninstallButtons(): HTMLButtonElement[] {
  return screen
    .getAllByText("pluginManager.uninstall")
    .map((label) => label.closest("button") as HTMLButtonElement);
}

beforeEach(() => {
  env.isMobile = false;
  env.columns = [
    {
      title: "pluginManager.title",
      dataIndex: "name",
      key: "name",
      render: (name: string) => <span data-testid="col-name">{name}</span>,
    },
  ];
});

afterEach(() => {
  cleanup();
});

describe("InstalledPluginList - toolbar", () => {
  it("renders the search box and the refresh action", () => {
    const props = renderList();
    expect(searchBox().value).toBe("");
    const refresh = screen.getByRole("button", {
      name: "pluginManager.catalogRefresh",
    });
    expect(refresh).not.toBeDisabled();
    fireEvent.click(refresh);
    expect(props.onRefresh).toHaveBeenCalledTimes(1);
  });

  it("disables refresh while the catalog is loading", () => {
    renderList({ loading: true });
    expect(
      screen.getByRole("button", { name: "pluginManager.catalogRefresh" }),
    ).toBeDisabled();
  });

  it("offers the view toggle on desktop only", () => {
    renderList();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    cleanup();

    env.isMobile = true;
    renderList();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
  });

  it("hides update-all until some plugin has an update", () => {
    renderList();
    expect(screen.queryByText("pluginManager.updateAll")).toBeNull();
    cleanup();

    renderList({ updates: new Map([["one", makeUpdate("2.0.0")]]) });
    expect(screen.getByText("pluginManager.updateAll")).toBeTruthy();
  });

  it("badges update-all with the number of updatable plugins", () => {
    renderList({
      updates: new Map([
        ["one", makeUpdate("2.0.0")],
        ["two", makeUpdate("3.0.0")],
      ]),
    });
    const button = screen
      .getByText("pluginManager.updateAll")
      .closest("button") as HTMLButtonElement;
    expect(within(button).getByText("2")).toBeTruthy();
  });

  it("shows the checking-updates notice only while checking", () => {
    renderList();
    expect(screen.queryByText("pluginManager.checkingUpdates")).toBeNull();
    cleanup();

    renderList({ updatesLoading: true });
    expect(screen.getByText("pluginManager.checkingUpdates")).toBeTruthy();
  });
});

describe("InstalledPluginList - search filtering", () => {
  it("keeps every plugin while the search box is empty", () => {
    renderList();
    expect(articles()).toHaveLength(2);
  });

  it("narrows the list by name, case-insensitively", () => {
    renderList();
    fireEvent.change(searchBox(), { target: { value: "PLUGIN ONE" } });
    expect(articles()).toHaveLength(1);
    expect(within(articles()[0]).getByText("Plugin one")).toBeTruthy();
  });

  it("ignores surrounding whitespace in the keyword", () => {
    renderList();
    fireEvent.change(searchBox(), { target: { value: "   two   " } });
    expect(articles()).toHaveLength(1);
    expect(within(articles()[0]).getByText("Plugin two")).toBeTruthy();
  });

  it("restores the full list when the keyword is cleared", () => {
    renderList();
    fireEvent.change(searchBox(), { target: { value: "one" } });
    expect(articles()).toHaveLength(1);
    fireEvent.change(searchBox(), { target: { value: "" } });
    expect(articles()).toHaveLength(2);
  });
});

describe("InstalledPluginList - empty states", () => {
  it("says there are no plugins when the catalog is empty", () => {
    renderList({ plugins: [] });
    expect(screen.getByText("pluginManager.noPlugins")).toBeTruthy();
    expect(screen.queryByText("pluginManager.noMatchingPlugins")).toBeNull();
  });

  it("says nothing matched when a search filtered everything out", () => {
    renderList();
    fireEvent.change(searchBox(), { target: { value: "zzz" } });
    expect(screen.getByText("pluginManager.noMatchingPlugins")).toBeTruthy();
    expect(screen.queryByText("pluginManager.noPlugins")).toBeNull();
  });

  it("keeps showing plugins while loading instead of an empty state", () => {
    renderList({ loading: true });
    expect(screen.queryByText("pluginManager.noPlugins")).toBeNull();
    expect(screen.queryByText("pluginManager.noMatchingPlugins")).toBeNull();
    expect(articles()).toHaveLength(2);
  });
});

describe("InstalledPluginList - card content", () => {
  it("labels each card with the plugin name and shows version and author", () => {
    renderList();
    const [first, second] = articles();
    expect(first.getAttribute("aria-label")).toBe("Plugin one");
    expect(within(first).getByText("v1.one.0 · Author one")).toBeTruthy();
    expect(within(first).getByText("Description for one")).toBeTruthy();
    // The second plugin has no author and no description, so both fall back.
    expect(second.getAttribute("aria-label")).toBe("Plugin two");
    expect(within(second).getByText("v1.two.0")).toBeTruthy();
    expect(within(second).getByText("market.noDescription")).toBeTruthy();
  });

  it("reports the loaded state per plugin", () => {
    renderList();
    const [first, second] = articles();
    expect(within(first).getByText("pluginManager.statusLoaded")).toBeTruthy();
    expect(
      within(second).getByText("pluginManager.statusUnloaded"),
    ).toBeTruthy();
  });

  it("always offers uninstall and hands the plugin object to the handler", () => {
    const props = renderList();
    const [first, second] = articles();
    fireEvent.click(within(first).getByText("pluginManager.uninstall"));
    expect(props.onUninstall).toHaveBeenCalledTimes(1);
    expect(props.onUninstall).toHaveBeenCalledWith(TWO_PLUGINS[0]);
    fireEvent.click(within(second).getByText("pluginManager.uninstall"));
    expect(props.onUninstall).toHaveBeenCalledTimes(2);
    expect(props.onUninstall).toHaveBeenLastCalledWith(TWO_PLUGINS[1]);
  });

  it("disables only the other uninstall buttons while one is in flight", () => {
    renderList({ uninstallingId: "one" });
    const [first, second] = articles();
    const firstButton = within(first)
      .getByText("pluginManager.uninstall")
      .closest("button") as HTMLButtonElement;
    const secondButton = within(second)
      .getByText("pluginManager.uninstall")
      .closest("button") as HTMLButtonElement;
    expect(firstButton).not.toBeDisabled();
    expect(secondButton).toBeDisabled();
  });

  it("falls back to the general type tag when a plugin declares none", () => {
    // `plugin.plugin_type ?? "general"` guards against a plugin whose manifest
    // omitted the type; PluginTypeTag renders "General" for that arm.
    renderList({
      plugins: [
        makePlugin("typed", { plugin_type: "tool" }),
        makePlugin("untyped", { plugin_type: undefined as never }),
      ],
    });
    const [typed, untyped] = articles();
    expect(within(typed).getByText("Tool")).toBeTruthy();
    expect(within(untyped).getByText("General")).toBeTruthy();
  });
});

describe("InstalledPluginList - per-plugin updates", () => {
  it("renders no update button for a plugin without an update", () => {
    renderList({ updates: new Map([["one", makeUpdate("2.0.0")]]) });
    const [first, second] = articles();
    expect(within(first).getByText("pluginManager.update")).toBeTruthy();
    expect(within(second).queryByText("pluginManager.update")).toBeNull();
  });

  it("hands the plugin object to onUpdate", () => {
    const props = renderList({
      updates: new Map([["one", makeUpdate("2.0.0")]]),
    });
    fireEvent.click(within(articles()[0]).getByText("pluginManager.update"));
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
    expect(props.onUpdate).toHaveBeenCalledWith(TWO_PLUGINS[0]);
  });

  it("hands update-all to onUpdateAll and disables it while checking", () => {
    const props = renderList({
      updates: new Map([["one", makeUpdate("2.0.0")]]),
      updatesLoading: true,
    });
    const all = screen
      .getByText("pluginManager.updateAll")
      .closest("button") as HTMLButtonElement;
    expect(all).toBeDisabled();
    cleanup();

    const props2 = renderList({
      updates: new Map([["one", makeUpdate("2.0.0")]]),
    });
    fireEvent.click(screen.getByText("pluginManager.updateAll"));
    expect(props2.onUpdateAll).toHaveBeenCalledTimes(1);
    expect(props.onUpdateAll).not.toHaveBeenCalled();
  });

  it("disables every per-plugin update while a full update runs", () => {
    renderList({
      updates: new Map([
        ["one", makeUpdate("2.0.0")],
        ["two", makeUpdate("3.0.0")],
      ]),
      updatingAll: true,
    });
    const [first, second] = articles();
    expect(
      within(first).getByText("pluginManager.update").closest("button"),
    ).toBeDisabled();
    expect(
      within(second).getByText("pluginManager.update").closest("button"),
    ).toBeDisabled();
  });

  it("disables only the other update buttons while one plugin updates", () => {
    renderList({
      updates: new Map([
        ["one", makeUpdate("2.0.0")],
        ["two", makeUpdate("3.0.0")],
      ]),
      updatingId: "one",
    });
    const [first, second] = articles();
    expect(
      within(first).getByText("pluginManager.update").closest("button"),
    ).not.toBeDisabled();
    expect(
      within(second).getByText("pluginManager.update").closest("button"),
    ).toBeDisabled();
  });
});

describe("InstalledPluginList - view modes", () => {
  it("starts in card view on desktop", () => {
    renderList();
    expect(articles()).toHaveLength(2);
    expect(screen.queryAllByTestId("col-name")).toHaveLength(0);
  });

  it("switches to the table view and back through the toggle", () => {
    renderList();
    switchToListView();
    expect(articles()).toHaveLength(0);
    // The table renders one name cell per filtered plugin.
    expect(screen.queryAllByTestId("col-name")).toHaveLength(2);
    expect(
      within(screen.queryAllByTestId("col-name")[0]).getByText("Plugin one"),
    ).toBeTruthy();

    fireEvent.click(screen.getAllByRole("tab")[1]);
    expect(articles()).toHaveLength(2);
    expect(screen.queryAllByTestId("col-name")).toHaveLength(0);
  });

  it("keeps the search filter applied across the view switch", () => {
    renderList();
    fireEvent.change(searchBox(), { target: { value: "two" } });
    switchToListView();
    expect(screen.queryAllByTestId("col-name")).toHaveLength(1);
  });

  it("falls back to the general type tag in the list branch too", () => {
    // The catalog rows build their own PluginTypeTag with the same
    // `plugin_type ?? "general"` guard as the cards. Card and list branches are
    // rendered either/or, and the mocked table column shows only the name, so
    // in list view this label can only come from the catalog row.
    renderList({
      plugins: [makePlugin("untyped2", { plugin_type: undefined as never })],
    });
    switchToListView();
    expect(articles()).toHaveLength(0);
    expect(screen.getByText("General")).toBeTruthy();
  });

  it("still hands the plugin object to the handlers from the list branch", () => {
    const props = renderList({
      updates: new Map([["two", makeUpdate("3.0.0")]]),
    });
    switchToListView();
    // The list branch renders its own uninstall and update buttons, so both
    // callbacks must work there too, not only in card view.
    const uninstalls = catalogUninstallButtons();
    expect(uninstalls).toHaveLength(2);
    fireEvent.click(uninstalls[0]);
    expect(props.onUninstall).toHaveBeenCalledTimes(1);
    expect(props.onUninstall).toHaveBeenCalledWith(TWO_PLUGINS[0]);

    // Only plugin two has an update, and only its own button exists.
    const updates = screen
      .getAllByText("pluginManager.update")
      .map((label) => label.closest("button") as HTMLButtonElement);
    expect(updates).toHaveLength(1);
    fireEvent.click(updates[0]);
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
    expect(props.onUpdate).toHaveBeenCalledWith(TWO_PLUGINS[1]);
    expect(uninstalls[1]).not.toBeDisabled();
  });

  it("disables only the other list-branch uninstall button while one is in flight", () => {
    renderList({ uninstallingId: "one" });
    switchToListView();
    const [first, second] = catalogUninstallButtons();
    expect(first).not.toBeDisabled();
    expect(second).toBeDisabled();
  });

  it("stays in card view on mobile regardless of the toggle state", () => {
    env.isMobile = true;
    renderList();
    // No toggle is rendered on mobile, and the card branch is forced.
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(articles()).toHaveLength(2);
    expect(screen.queryAllByTestId("col-name")).toHaveLength(0);
  });
});
