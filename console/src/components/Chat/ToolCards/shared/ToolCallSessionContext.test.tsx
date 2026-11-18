// @vitest-environment jsdom
/**
 * ToolCallSessionContext tests.
 *
 * The module under test is a one-line hook wrapper:
 * `useToolCallSessionId()` returns `resolveBackendSessionId()` with no
 * argument. Its callers are the tool-call control APIs, reached from
 * `ToolCardShell.tsx:73` and re-exported through the barrel
 * `ToolCards/shared/index.ts:3`.
 *
 * Visible contract under test:
 *
 *   1. the hook reports the *backend* session id of the currently active chat,
 *      mapped through `sessionApi` exactly as `resolveBackendSessionId` maps it;
 *   2. it never invents an id: with no active chat it reports the empty string
 *      rather than a placeholder or a local library id;
 *   3. it reads the active chat at call time, so a chat switch between renders
 *      is picked up instead of being captured on the first render;
 *   4. an active id that has no backend mapping at all still yields the empty
 *      string (the doc comment promises "never a bare local library id");
 *   5. the hook takes no caller-supplied id: the only id ever handed to
 *      `sessionApi` is the active one, so a card cannot leak its own local id
 *      into a control API;
 *   6. it needs no React provider around it, which is why it exists as a hook
 *      instead of a context - `renderHook` without a wrapper must work.
 *
 * Harness notes (measured facts):
 *
 * - `sessionApi` is stubbed the same way `src/utils/resolveBackendSessionId.test.ts`
 *   stubs it (default export with `lastActiveChatId`, `getBackendSessionId`,
 *   `getRealIdForSession`), so this suite exercises the real
 *   `resolveBackendSessionId` logic rather than a mock of it.
 * - The stub maps ids prefixed `known-`/`local-` to `mapped:<id>` and leaves
 *   every other id unchanged, mirroring the real `sessionApi` behaviour that
 *   sibling suite documents.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const defaultGetBackendSessionId = (id: string) => {
  // Mirror sessionApi: unknown ids stay unchanged; known/local map.
  if (id.startsWith("known-") || id.startsWith("local-")) {
    return `mapped:${id}`;
  }
  return id;
};
const defaultGetRealIdForSession = (id: string) =>
  id.startsWith("known-") ? `real-${id}` : null;

const getBackendSessionId = vi.fn(defaultGetBackendSessionId);
const getRealIdForSession = vi.fn(defaultGetRealIdForSession);

vi.mock("../../../../pages/Chat/sessionApi", () => ({
  default: {
    lastActiveChatId: "known-active",
    getBackendSessionId: (id: string) => getBackendSessionId(id),
    getRealIdForSession: (id: string) => getRealIdForSession(id),
  },
}));

import sessionApi from "../../../../pages/Chat/sessionApi";
import { useToolCallSessionId } from "./ToolCallSessionContext";

describe("useToolCallSessionId", () => {
  beforeEach(() => {
    // Restore the default stub behaviour: one case below swaps the
    // implementation wholesale, and mockClear() alone would leak that swap
    // into every later case (it clears call records, not implementations).
    getBackendSessionId.mockReset();
    getBackendSessionId.mockImplementation(defaultGetBackendSessionId);
    getRealIdForSession.mockReset();
    getRealIdForSession.mockImplementation(defaultGetRealIdForSession);
    sessionApi.lastActiveChatId = "known-active";
  });

  it("reports the backend id of the active chat", () => {
    const { result } = renderHook(() => useToolCallSessionId());

    expect(result.current).toBe("mapped:known-active");
  });

  it("reports the empty string when there is no active chat", () => {
    sessionApi.lastActiveChatId = null;

    const { result } = renderHook(() => useToolCallSessionId());

    expect(result.current).toBe("");
  });

  it("picks up a chat switch made between renders", () => {
    const { result, rerender } = renderHook(() => useToolCallSessionId());
    expect(result.current).toBe("mapped:known-active");

    sessionApi.lastActiveChatId = "known-second";
    rerender();

    expect(result.current).toBe("mapped:known-second");
  });

  it("reports the empty string when the active id has no backend mapping", () => {
    sessionApi.lastActiveChatId = "unmapped-1";
    getBackendSessionId.mockImplementation(() => "");

    const { result } = renderHook(() => useToolCallSessionId());

    expect(result.current).toBe("");
  });

  it("only ever asks sessionApi about the active chat id", () => {
    renderHook(() => useToolCallSessionId());

    const asked = getBackendSessionId.mock.calls.map((call) => call[0]);
    expect(asked.length).toBeGreaterThan(0);
    expect(new Set(asked)).toEqual(new Set(["known-active"]));
  });

  it("works without any React provider around it", () => {
    const { result } = renderHook(() => useToolCallSessionId());

    expect(typeof result.current).toBe("string");
    expect(result.current).not.toBe("");
  });
});
