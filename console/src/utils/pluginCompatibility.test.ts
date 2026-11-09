/**
 * Unit tests for the market plugin compatibility check.
 *
 * What this file pins:
 * - The four independent escape hatches that all return `true` (no client
 *   version, no labels, empty labels, unparseable version). Collapsing any of
 *   them into "incompatible" would hide every plugin from the market list, so
 *   each one is asserted separately.
 * - deriveCompatLabel's normalisation: a leading `v` is dropped and only the
 *   major segment survives, so `v1.2.3` matches the label `1.x` while `10.0`
 *   does not match `1.x`.
 * - Whitespace tolerance on the version string (it comes from a settings call).
 * - The membership test is exact: an entry listing `2.x` is not compatible
 *   with a `1.x` client, and a label that merely contains the derived string
 *   (e.g. `11.x` vs `1.x`) must not be treated as a match.
 */
import { describe, expect, it } from "vitest";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { isMarketPluginCompatible } from "./pluginCompatibility";

const entry = (
  labels: string[] | undefined,
  overrides: Partial<MarketPluginEntry> = {},
): MarketPluginEntry =>
  ({
    id: "plugin-one",
    display_name: "Plugin One",
    developer: "dev",
    owner: "owner",
    version: "0.9.1",
    logo_url: null,
    downloads: 3,
    view_count: 4,
    details_url: null,
    locales: {},
    qwenpaw_compat_labels: labels,
    ...overrides,
  }) as MarketPluginEntry;

describe("isMarketPluginCompatible", () => {
  it("accepts everything when the client version is null", () => {
    expect(isMarketPluginCompatible(entry(["9.x"]), null)).toBe(true);
  });

  it("accepts everything when the client version is an empty string", () => {
    expect(isMarketPluginCompatible(entry(["9.x"]), "")).toBe(true);
  });

  it("accepts an entry with no compat labels at all", () => {
    expect(isMarketPluginCompatible(entry(undefined), "1.2.3")).toBe(true);
  });

  it("accepts an entry with an empty compat label list", () => {
    expect(isMarketPluginCompatible(entry([]), "1.2.3")).toBe(true);
  });

  it("accepts every entry when the client version cannot be parsed", () => {
    // No leading digits, so deriveCompatLabel returns null and the check is
    // skipped rather than failing closed.
    expect(isMarketPluginCompatible(entry(["1.x"]), "nightly")).toBe(true);
    expect(isMarketPluginCompatible(entry(["1.x"]), "v")).toBe(true);
  });

  it("matches the major segment derived from a plain version", () => {
    expect(isMarketPluginCompatible(entry(["1.x"]), "1.2.3")).toBe(true);
  });

  it("matches after dropping a leading v", () => {
    expect(isMarketPluginCompatible(entry(["1.x"]), "v1.2.3")).toBe(true);
    expect(isMarketPluginCompatible(entry(["2.x"]), "V2.0.0")).toBe(true);
  });

  it("ignores surrounding whitespace in the client version", () => {
    expect(isMarketPluginCompatible(entry(["1.x"]), "  1.4.0  ")).toBe(true);
  });

  it("rejects an entry that only lists a different major", () => {
    expect(isMarketPluginCompatible(entry(["2.x"]), "1.2.3")).toBe(false);
  });

  it("rejects when the label list does not contain the derived major", () => {
    expect(isMarketPluginCompatible(entry(["1.x", "3.x"]), "2.0.0")).toBe(
      false,
    );
  });

  it("accepts when any listed label matches", () => {
    expect(isMarketPluginCompatible(entry(["1.x", "2.x"]), "2.9.9")).toBe(true);
  });

  it("does not treat a longer major as a prefix match", () => {
    // "11.x".includes("1.x") would be true for a substring test; the real check
    // is membership, so an 11.x entry must not satisfy a 1.x client.
    expect(isMarketPluginCompatible(entry(["11.x"]), "1.0.0")).toBe(false);
    expect(isMarketPluginCompatible(entry(["1.x"]), "11.0.0")).toBe(false);
  });

  it("derives the label from the major only, ignoring minor and patch", () => {
    expect(isMarketPluginCompatible(entry(["1.x"]), "1.99.99")).toBe(true);
    expect(isMarketPluginCompatible(entry(["10.x"]), "10.0.0")).toBe(true);
  });
});
