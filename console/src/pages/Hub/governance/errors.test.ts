import { describe, it, expect, vi } from "vitest";
import { governanceErrorMessage } from "./errors";
import type { TFunction } from "i18next";

/**
 * governanceErrorMessage maps a backend detail string onto a translation key.
 * The fake t echoes the key it was asked for, which keeps every assertion about
 * the mapping itself rather than about locale content.
 */

function makeT() {
  const t = vi.fn((key: string) => `T:${key}`) as unknown as TFunction;
  return { t, spy: t as unknown as ReturnType<typeof vi.fn> };
}

describe("governanceErrorMessage — known backend details", () => {
  it.each([
    ["Hub request failed", "requestFailed"],
    ["Failed to fetch", "requestFailed"],
    ["NetworkError when attempting to fetch resource.", "requestFailed"],
    ["Load failed", "requestFailed"],
    ["Configuration changed; refresh before saving", "changed"],
    ["Policy changed; refresh before saving", "changed"],
    ["An API key is required for a new connection", "keyRequired"],
    ["Connection does not exist", "connectionMissing"],
    ["Connection not found", "connectionMissing"],
    ["Unknown member", "memberMissing"],
    ["Unknown budget member", "memberMissing"],
    ["User not found", "memberMissing"],
    ["Budget timezone is fixed after first use", "timezoneFixed"],
    ["Choose an enabled all-member default", "defaultUnavailable"],
    ["Model is unavailable or not authorized", "modelUnavailable"],
    ["Batch already created; codes cannot replay", "batchExists"],
    ["Unknown model grant", "grantMissing"],
    ["Account is disabled", "accountDisabled"],
    ["Model budget bounds are unverified", "boundsUnverified"],
    ["Model provider connection is disabled", "connectionDisabled"],
    ["hub_model_unavailable", "modelUnavailable"],
    ["hub_budget_exceeded", "budgetExceeded"],
    ["Only ordinary member passwords can reset", "passwordMemberOnly"],
  ])("maps %j to the %s key", (detail, key) => {
    const { t } = makeT();
    expect(governanceErrorMessage(new Error(detail), t)).toBe(
      `T:hub.governance.errors.${key}`,
    );
  });

  it("collapses several network phrasings onto one request failure key", () => {
    const { t } = makeT();
    const phrasings = [
      "Hub request failed",
      "Failed to fetch",
      "NetworkError when attempting to fetch resource.",
      "Load failed",
    ];
    const results = phrasings.map((detail) =>
      governanceErrorMessage(new Error(detail), t),
    );
    expect(new Set(results).size).toBe(1);
  });
});

describe("governanceErrorMessage — discovery failure special case", () => {
  it("uses a dedicated key instead of the generic error map", () => {
    const { t } = makeT();
    expect(
      governanceErrorMessage(new Error("hub_model_discovery_failed"), t),
    ).toBe("T:hub.governance.models.discoveryFailed");
  });

  it("recognises the discovery detail on a bare string too", () => {
    const { t } = makeT();
    expect(governanceErrorMessage("hub_model_discovery_failed", t)).toBe(
      "T:hub.governance.models.discoveryFailed",
    );
  });
});

describe("governanceErrorMessage — input shapes", () => {
  it("reads the message from an Error instance", () => {
    const { t } = makeT();
    expect(governanceErrorMessage(new Error("Connection not found"), t)).toBe(
      "T:hub.governance.errors.connectionMissing",
    );
  });

  it("accepts a plain string error", () => {
    const { t } = makeT();
    expect(governanceErrorMessage("Unknown member", t)).toBe(
      "T:hub.governance.errors.memberMissing",
    );
  });

  it("preserves an unknown detail verbatim so the operator can read it", () => {
    const { t, spy } = makeT();
    expect(governanceErrorMessage("disk on fire", t)).toBe("disk on fire");
    expect(spy).not.toHaveBeenCalled();
  });

  it("falls back to the generic request failure key for an empty message", () => {
    const { t } = makeT();
    expect(governanceErrorMessage(new Error(""), t)).toBe(
      "T:hub.governance.errors.requestFailed",
    );
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
  ])("falls back to the generic key for %s", (_label, value) => {
    const { t } = makeT();
    expect(governanceErrorMessage(value, t)).toBe(
      "T:hub.governance.errors.requestFailed",
    );
  });

  it("stringifies a non Error object rather than throwing", () => {
    const { t } = makeT();
    const result = governanceErrorMessage({ detail: "x" }, t);
    expect(result).toBe("[object Object]");
  });

  it("keeps a numeric error code readable", () => {
    const { t } = makeT();
    expect(governanceErrorMessage(500, t)).toBe("500");
  });

  it("treats a zero code as a readable detail rather than a missing one", () => {
    // String(0) is "0", which is a truthy string, so the generic fallback does
    // not kick in the way it does for null and undefined.
    const { t, spy } = makeT();
    expect(governanceErrorMessage(0, t)).toBe("0");
    expect(spy).not.toHaveBeenCalled();
  });

  it("prefers an Error subclass message over its type name", () => {
    const { t } = makeT();
    expect(governanceErrorMessage(new TypeError("Failed to fetch"), t)).toBe(
      "T:hub.governance.errors.requestFailed",
    );
  });
});
