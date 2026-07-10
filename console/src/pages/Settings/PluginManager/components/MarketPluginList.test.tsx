// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { invoke, isTauri } from "@/test/tauri-mock";
import { MarketPluginList } from "./MarketPluginList";

const hoisted = vi.hoisted(() => ({
  plugins: [] as MarketPluginEntry[],
  handleInstall: vi.fn(),
}));

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
    installingId: null,
    qwenpawVersion: "2.0.0",
    isCompatible: () => true,
    handleSearch: vi.fn(),
    handleCategoryChange: vi.fn(),
    handlePageChange: vi.fn(),
    handleRefresh: vi.fn(),
    handleInstall: hoisted.handleInstall,
  }),
}));

function makePlugin(detailsUrl: string): MarketPluginEntry {
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
    hoisted.plugins.length = 0;
    hoisted.handleInstall.mockReset();
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
});
