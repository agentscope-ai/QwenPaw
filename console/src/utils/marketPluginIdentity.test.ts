import { describe, expect, it } from "vitest";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { marketPluginMatches } from "./marketPluginIdentity";

function entry(overrides: Partial<MarketPluginEntry> = {}): MarketPluginEntry {
  return {
    id: "@owner/example",
    display_name: "Example",
    developer: "owner",
    owner: "owner",
    version: "1.0.0",
    logo_url: null,
    downloads: 0,
    view_count: 0,
    details_url: null,
    locales: {},
    ...overrides,
  };
}

describe("marketPluginMatches", () => {
  it("matches a package short ID when its author owns the market entry", () => {
    expect(
      marketPluginMatches(
        { id: "qwenpaw-thinking-collapse", author: "erickcharles" },
        entry({
          id: "@erickcharles/qwenpaw-thinking-collapse",
          owner: "erickcharles",
          developer: "erickcharles",
        }),
      ),
    ).toBe(true);
  });

  it("does not match same-name plugins from another author", () => {
    expect(
      marketPluginMatches({ id: "example", author: "other-owner" }, entry()),
    ).toBe(false);
  });

  it("matches exact scoped IDs without requiring author metadata", () => {
    expect(marketPluginMatches({ id: "@owner/example" }, entry())).toBe(true);
  });
});
