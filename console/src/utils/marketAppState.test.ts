import { describe, expect, it } from "vitest";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import {
  getInstalledMarketAppVersion,
  getMarketAppState,
} from "./marketAppState";

function makeEntry(
  overrides: Partial<MarketPluginEntry> = {},
): MarketPluginEntry {
  return {
    id: "@owner/app",
    display_name: "App",
    developer: "owner",
    owner: "owner",
    version: "1.0.0",
    logo_url: null,
    downloads: 0,
    view_count: 0,
    details_url: null,
    locales: { en: { description: "App", category: "app" } },
    ...overrides,
  };
}

describe("market app state", () => {
  it("matches community entries only by their exact ID", () => {
    const entry = makeEntry();
    expect(
      getInstalledMarketAppVersion(entry, new Map([["app", "1.0.0"]])),
    ).toBeNull();
    expect(getMarketAppState(entry, new Map([["@owner/app", "1.0.0"]]))).toBe(
      "installed",
    );
  });

  it("allows official entries to match their bundled app ID", () => {
    const entry = makeEntry({ id: "@agentscope/qwenpaw-creator" });
    expect(
      getInstalledMarketAppVersion(
        entry,
        new Map([["qwenpaw-creator", "1.0.0"]]),
        "official",
      ),
    ).toBe("1.0.0");
  });

  it("marks a newer market version as an update", () => {
    const entry = makeEntry({ version: "1.1.0" });
    expect(getMarketAppState(entry, new Map([["@owner/app", "1.0.0"]]))).toBe(
      "update",
    );
  });

  it("offers an update when the market version differs", () => {
    const entry = makeEntry({ version: "0.9.0" });
    expect(getMarketAppState(entry, new Map([["@owner/app", "1.0.0"]]))).toBe(
      "update",
    );
  });
});
