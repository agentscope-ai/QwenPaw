/**
 * Tool-call APIs validate the session_id against the running entry and
 * return 404 on mismatch, so resolveBackendSessionId must resolve strictly:
 * an id that cannot be confirmed against the session list yields "" (the
 * callers retry with backoff) instead of leaking the raw stale id.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const getBackendSessionIdStrict = vi.fn((id: string) => {
  if (!id) return "";
  // Mirror sessionApi strict mapping: an id that already IS a backend
  // session_id passes through; known library ids map; unknown -> "".
  if (id === "console:default") return "console:default";
  if (id === "lib-mapped") return "console:default";
  if (id === "known-last-active") return "console:active";
  if (id === "known-win-sid") return "console:win";
  return "";
});
const isKnownBackendSessionId = vi.fn(
  (id: string) => id === "console:default",
);

vi.mock("../pages/Chat/sessionApi", () => ({
  default: {
    lastActiveChatId: null as string | null,
    getBackendSessionIdStrict: (id: string) => getBackendSessionIdStrict(id),
    isKnownBackendSessionId: (id: string) => isKnownBackendSessionId(id),
  },
}));

import sessionApi from "../pages/Chat/sessionApi";
import { resolveBackendSessionId } from "./resolveBackendSessionId";

describe("resolveBackendSessionId", () => {
  beforeEach(() => {
    getBackendSessionIdStrict.mockClear();
    isKnownBackendSessionId.mockClear();
    sessionApi.lastActiveChatId = null;
    delete (window as unknown as { currentSessionId?: string })
      .currentSessionId;
  });

  it("passes a known backend session_id through unchanged", () => {
    expect(resolveBackendSessionId("console:default")).toBe(
      "console:default",
    );
  });

  it("maps a known library id to its backend session_id", () => {
    expect(resolveBackendSessionId("lib-mapped")).toBe("console:default");
    expect(getBackendSessionIdStrict).toHaveBeenCalledWith("lib-mapped");
  });

  it('returns "" for an unknown id instead of leaking it', () => {
    // A stale chat UUID that is no longer in the session list must not be
    // sent to validating endpoints.
    expect(resolveBackendSessionId("2cbdb459-91ff-4a02-acd3-efd7df52ddad"))
      .toBe("");
  });

  it("falls back to lastActiveChatId when preferred is empty", () => {
    sessionApi.lastActiveChatId = "known-last-active";
    expect(resolveBackendSessionId("")).toBe("console:active");
    expect(resolveBackendSessionId(null)).toBe("console:active");
  });

  it("falls back to window.currentSessionId only when it resolves", () => {
    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "known-win-sid";
    expect(resolveBackendSessionId(null)).toBe("console:win");

    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "stale-win";
    expect(resolveBackendSessionId(null)).toBe("");
  });
});
