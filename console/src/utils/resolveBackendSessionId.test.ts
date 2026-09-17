import { beforeEach, describe, expect, it, vi } from "vitest";

const getBackendSessionId = vi.fn((id: string) => {
  // Mirror sessionApi: unknown ids stay unchanged; known/local map.
  if (id.startsWith("known-") || id.startsWith("local-")) {
    return `mapped:${id}`;
  }
  return id;
});
const getRealIdForSession = vi.fn((id: string) =>
  id.startsWith("known-") ? `real-${id}` : null,
);

vi.mock("../pages/Chat/sessionApi", () => ({
  default: {
    lastActiveChatId: "known-last-active",
    getBackendSessionId: (id: string) => getBackendSessionId(id),
    getRealIdForSession: (id: string) => getRealIdForSession(id),
  },
}));

import sessionApi from "../pages/Chat/sessionApi";
import { resolveBackendSessionId } from "./resolveBackendSessionId";

describe("resolveBackendSessionId", () => {
  beforeEach(() => {
    getBackendSessionId.mockClear();
    getRealIdForSession.mockClear();
    sessionApi.lastActiveChatId = "known-last-active";
    delete (window as unknown as { currentSessionId?: string })
      .currentSessionId;
  });

  it("maps an explicit preferred id through sessionApi", () => {
    expect(resolveBackendSessionId("local-123")).toBe("mapped:local-123");
    expect(getBackendSessionId).toHaveBeenCalledWith("local-123");
  });

  it("prefers lastActiveChatId over window.currentSessionId", () => {
    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "known-win-sid";
    expect(resolveBackendSessionId("")).toBe("mapped:known-last-active");
    expect(getBackendSessionId).toHaveBeenCalledWith("known-last-active");
  });

  it("falls back to window only when known in the session list", () => {
    sessionApi.lastActiveChatId = null;
    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "known-win-sid";
    expect(resolveBackendSessionId(null)).toBe("mapped:known-win-sid");

    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "stale-win";
    expect(resolveBackendSessionId(null)).toBe("");
  });
});
