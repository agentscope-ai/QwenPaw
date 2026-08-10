// @vitest-environment jsdom
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { invoke, isTauri } from "@/test/tauri-mock";
import { MarketPluginList } from "./MarketPluginList";

const hoisted = vi.hoisted(() => ({
  plugins: [] as MarketPluginEntry[],
  handleInstall: vi.fn(),
  handleSortChange: vi.fn(),
  handleLoadMore: vi.fn(),
  hasMore: false,
}));

let intersectionCallbacks: IntersectionObserverCallback[] = [];

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../hooks/useMarketPlugins", () => ({
  useMarketPlugins: () => ({
    loading: false,
    error: null,
    plugins: hoisted.plugins,
    total: hoisted.plugins.length,
    page: 1,
    pageSize: 20,
    category: undefined,
    sortBy: "downloads",
    loadingMore: false,
    hasMore: hoisted.hasMore,
    autoLoadBlocked: false,
    installingId: null,
    qwenpawVersion: "2.0.0",
    isCompatible: () => true,
    handleSearch: vi.fn(),
    handleCategoryChange: vi.fn(),
    handleSortChange: hoisted.handleSortChange,
    handleRefresh: vi.fn(),
    handleLoadMore: hoisted.handleLoadMore,
    handleRetryLoadMore: vi.fn(),
    handleInstall: hoisted.handleInstall,
  }),
}));

function makePlugin(
  detailsUrl: string,
  qwenpawCompatLabels?: string[],
): MarketPluginEntry {
  return {
    id: "@agentscope/demo",
    display_name: "Demo plugin",
    developer: "AgentScope",
    owner: "agentscope",
    version: "1.0.0",
    logo_url: null,
    downloads: 10,
    view_count: 20,
    details_url: detailsUrl,
    qwenpaw_compat_labels: qwenpawCompatLabels,
    locales: {
      en: {
        description: "Demo description",
        category: "General",
      },
    },
  };
}

describe("MarketPluginList", () => {
  const windowOpen = vi.fn();

  beforeEach(() => {
    intersectionCallbacks = [];
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: IntersectionObserverCallback) {
          intersectionCallbacks.push(callback);
        }

        observe() {}
        disconnect() {}
      },
    );
    hoisted.plugins.length = 0;
    hoisted.hasMore = false;
    hoisted.handleInstall.mockReset();
    hoisted.handleSortChange.mockReset();
    hoisted.handleLoadMore.mockReset();
    invoke.mockReset();
    invoke.mockResolvedValue(undefined);
    isTauri.mockReturnValue(false);
    windowOpen.mockReset();
    vi.spyOn(window, "open").mockImplementation(windowOpen);
    window.history.replaceState(null, "", "/");
    delete (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  });

  it("opens plugin details through the shared external-link guard", () => {
    hoisted.plugins.push(
      makePlugin("https://platform.agentscope.io/plugins/agentscope/demo"),
    );

    render(<MarketPluginList onInstalled={vi.fn()} />);
    fireEvent.click(screen.getByText("pluginManager.marketDetails"));

    expect(windowOpen).toHaveBeenCalledWith(
      "https://platform.agentscope.io/plugins/agentscope/demo",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("does not open unsupported plugin details URL schemes", () => {
    hoisted.plugins.push(makePlugin("javascript:alert(1)"));

    render(<MarketPluginList onInstalled={vi.fn()} />);
    fireEvent.click(screen.getByText("pluginManager.marketDetails"));

    expect(windowOpen).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalled();
  });

  it("shows the QwenPaw compatibility versions returned by the market", () => {
    hoisted.plugins.push(
      makePlugin("https://platform.agentscope.io/plugins/agentscope/demo", [
        "1.x",
        "2.x",
      ]),
    );

    render(<MarketPluginList onInstalled={vi.fn()} />);

    expect(screen.getByText("QwenPaw 1.x, 2.x")).toBeInTheDocument();
  });

  it("renders cards by default and keeps the existing list view available", () => {
    hoisted.plugins.push(
      makePlugin("https://platform.agentscope.io/plugins/agentscope/demo"),
    );

    render(<MarketPluginList onInstalled={vi.fn()} />);

    expect(
      screen.getByRole("article", { name: "Demo plugin" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("skills.listView"));

    expect(
      screen.queryByRole("article", { name: "Demo plugin" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Demo plugin")).toBeInTheDocument();
  });

  it("loads the next page when the bottom sentinel becomes visible", async () => {
    hoisted.plugins.push(
      makePlugin("https://platform.agentscope.io/plugins/agentscope/demo"),
    );
    hoisted.hasMore = true;

    render(<MarketPluginList onInstalled={vi.fn()} />);

    await waitFor(() => expect(intersectionCallbacks).toHaveLength(1));
    act(() => {
      intersectionCallbacks[0](
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    expect(hoisted.handleLoadMore).toHaveBeenCalledTimes(1);
  });

  it("changes the plugin market sort order", () => {
    render(<MarketPluginList onInstalled={vi.fn()} />);

    fireEvent.mouseDown(
      screen.getByRole("combobox", {
        name: "pluginManager.marketSortLabel",
      }),
    );
    fireEvent.click(screen.getByText("pluginManager.marketSortUpdated"));

    expect(hoisted.handleSortChange.mock.calls[0]?.[0]).toBe("updated_time");
  });
});
