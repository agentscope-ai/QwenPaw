import { act, renderHook } from "@testing-library/react";
import { App } from "antd";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

vi.mock("antd", () => {
  const App = {
    useApp: vi.fn(),
  };
  return { App };
});

// Both values must be referentially stable. The hook lists `t` in a
// useCallback dependency array, and that callback drives the mount fetch
// effect: handing back a fresh function on every render re-creates the
// callback, re-runs the effect, and issues a second backend call per mount
// (measured with a throwaway probe: 2 calls instead of 1). That silently broke
// every error-path case, because mockRejectedValueOnce only rejects the first
// of the two calls and the second one clears the error again.
const { stableT, stableI18n } = vi.hoisted(() => ({
  stableT: (key: string, fallback?: string) => fallback ?? key,
  stableI18n: { resolvedLanguage: "en", language: "en" },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: stableT, i18n: stableI18n }),
}));

vi.mock("../../../api/modules/debug", () => ({
  debugApi: {
    getBackendLogs: vi.fn(),
  },
}));

import {
  debugApi,
  type BackendDebugLogsResponse,
} from "../../../api/modules/debug";
import { backendLevelColor, useDebugLogs } from "./useDebugLogs";

const getBackendLogs = debugApi.getBackendLogs as Mock;

// Mirrors the shape the backend returns; `content` is the only field the hook
// derives behaviour from, the rest are passed through untouched.
const logsResponse = (content: string): BackendDebugLogsResponse => ({
  path: "/tmp/backend.log",
  exists: true,
  lines: 200,
  updated_at: 1700000000,
  size: content.length,
  content,
});

let messageApi: { success: Mock; error: Mock };

describe("backendLevelColor", () => {
  it("maps every known level to its badge colour", () => {
    expect(backendLevelColor("error")).toBe("red");
    expect(backendLevelColor("warning")).toBe("gold");
    expect(backendLevelColor("info")).toBe("blue");
    expect(backendLevelColor("debug")).toBe("geekblue");
  });

  it("falls back to the neutral colour for the all-levels filter", () => {
    expect(backendLevelColor("all")).toBe("default");
  });
});

describe("useDebugLogs", () => {
  beforeEach(() => {
    messageApi = { success: vi.fn(), error: vi.fn() };
    (App.useApp as Mock).mockReturnValue({ message: messageApi });
    getBackendLogs.mockReset();
    getBackendLogs.mockResolvedValue(logsResponse("2026-09-15 INFO started"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  // ── initial load ────────────────────────────────────────────────────────

  it("requests the log tail on mount and clears the initial loading flag", async () => {
    const { result } = renderHook(() => useDebugLogs());

    expect(result.current.initialLoading).toBe(true);

    await act(async () => {
      await Promise.resolve();
    });

    // 200 is the line budget the hook hard-codes for the backend request.
    expect(getBackendLogs).toHaveBeenCalledWith(200);
    expect(result.current.initialLoading).toBe(false);
    expect(result.current.backendLogs?.content).toBe("2026-09-15 INFO started");
    expect(result.current.backendError).toBe("");
  });

  it("does not raise a toast for the automatic first load", async () => {
    renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(messageApi.success).not.toHaveBeenCalled();
    expect(messageApi.error).not.toHaveBeenCalled();
  });

  it("keeps the loading flag up only until the very first fetch settles", async () => {
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.initialLoading).toBe(false);

    // A later manual refresh must not flip the flag back on: it drives the
    // first-paint skeleton only.
    await act(async () => {
      await result.current.loadBackendLogs();
    });
    expect(result.current.initialLoading).toBe(false);
    expect(getBackendLogs).toHaveBeenCalledTimes(2);
  });

  // ── error paths ─────────────────────────────────────────────────────────

  it("surfaces the thrown message when the request rejects with an Error", async () => {
    getBackendLogs.mockRejectedValueOnce(new Error("gateway 502"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.backendError).toBe("gateway 502");
    // The failed first fetch still ends the skeleton state.
    expect(result.current.initialLoading).toBe(false);
  });

  it("falls back to the translated copy when the rejection is not an Error", async () => {
    getBackendLogs.mockRejectedValueOnce("boom");
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.backendError).toBe("Failed to load backend logs");
  });

  it("clears a previous error once a later fetch succeeds", async () => {
    getBackendLogs.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.backendError).toBe("offline");

    await act(async () => {
      await result.current.loadBackendLogs();
    });
    expect(result.current.backendError).toBe("");
  });

  // ── explicit refresh toasts ─────────────────────────────────────────────

  it("confirms an explicitly requested refresh with a success toast", async () => {
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await result.current.loadBackendLogs({ successToast: true });
    });

    expect(messageApi.success).toHaveBeenCalledWith("Logs refreshed");
    expect(messageApi.error).not.toHaveBeenCalled();
  });

  it("reports an explicitly requested refresh failure with an error toast", async () => {
    const { result } = renderHook(() => useDebugLogs());

    // Let the automatic mount fetch settle first: it carries no toast, and
    // arming the rejection before it would spend the `once` on the wrong call.
    await act(async () => {
      await Promise.resolve();
    });

    getBackendLogs.mockRejectedValueOnce(new Error("disk full"));

    await act(async () => {
      await result.current.loadBackendLogs({ successToast: true });
    });

    expect(messageApi.error).toHaveBeenCalledWith("disk full");
    expect(messageApi.success).not.toHaveBeenCalled();
    expect(result.current.backendError).toBe("disk full");
  });

  it("uses the translated copy in the error toast for non-Error rejections", async () => {
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    getBackendLogs.mockRejectedValueOnce(null);

    await act(async () => {
      await result.current.loadBackendLogs({ successToast: true });
    });

    expect(messageApi.error).toHaveBeenCalledWith(
      "Failed to load backend logs",
    );
    expect(result.current.backendError).toBe("Failed to load backend logs");
  });

  // ── auto refresh polling ────────────────────────────────────────────────

  it("polls on the refresh interval while auto refresh is on", async () => {
    vi.useFakeTimers();
    renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });
    const afterMount = getBackendLogs.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(getBackendLogs.mock.calls.length).toBe(afterMount + 1);
  });

  it("stops polling once auto refresh is switched off", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setAutoRefresh(false);
    });
    const afterDisable = getBackendLogs.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });

    expect(getBackendLogs.mock.calls.length).toBe(afterDisable);
    expect(result.current.autoRefresh).toBe(false);
  });

  it("does not schedule a further tick when auto refresh is turned off mid-flight", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    // Start the interval, then disable while the in-flight fetch resolves: the
    // cancelled flag must swallow the follow-up scheduling.
    act(() => {
      result.current.setAutoRefresh(true);
    });
    act(() => {
      result.current.setAutoRefresh(false);
    });
    const settled = getBackendLogs.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });

    expect(getBackendLogs.mock.calls.length).toBe(settled);
  });

  // ── line splitting and ordering ─────────────────────────────────────────

  it("reverses the tail so the newest line comes first by default", async () => {
    getBackendLogs.mockResolvedValue(logsResponse("first\nsecond\nthird"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.backendNewestFirst).toBe(true);
    expect(result.current.filteredBackendLines).toEqual([
      "third",
      "second",
      "first",
    ]);
  });

  it("keeps the backend order when newest-first is switched off", async () => {
    getBackendLogs.mockResolvedValue(logsResponse("first\nsecond\nthird"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setBackendNewestFirst(false);
    });

    expect(result.current.filteredBackendLines).toEqual([
      "first",
      "second",
      "third",
    ]);
  });

  it("treats a blank log body as having no lines at all", async () => {
    getBackendLogs.mockResolvedValue(logsResponse("   \n  "));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.filteredBackendLines).toEqual([]);
  });

  it("handles a null payload before the first response lands", async () => {
    getBackendLogs.mockResolvedValueOnce(
      undefined as unknown as BackendDebugLogsResponse,
    );
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.backendLogs).toBeUndefined();
    expect(result.current.filteredBackendLines).toEqual([]);
  });

  // ── level filtering ─────────────────────────────────────────────────────

  const LEVEL_FIXTURE = [
    "2026-09-15 10:00:00 INFO  service up",
    "2026-09-15 10:00:01 | ERROR | db unreachable",
    "2026-09-15 10:00:02 WARNING disk almost full",
    "2026-09-15 10:00:03 DEBUG cache miss",
  ].join("\n");

  it("keeps every line while the level filter is set to all", async () => {
    getBackendLogs.mockResolvedValue(logsResponse(LEVEL_FIXTURE));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.backendLevel).toBe("all");
    expect(result.current.filteredBackendLines).toHaveLength(4);
  });

  it.each([
    ["info", "service up"],
    ["error", "db unreachable"],
    ["warning", "disk almost full"],
    ["debug", "cache miss"],
  ] as const)(
    "matches the %s level across all three separator layouts",
    async (level, needle) => {
      getBackendLogs.mockResolvedValue(logsResponse(LEVEL_FIXTURE));
      const { result } = renderHook(() => useDebugLogs());

      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        result.current.setBackendLevel(level);
      });

      expect(result.current.backendLevel).toBe(level);
      expect(result.current.filteredBackendLines).toHaveLength(1);
      expect(result.current.filteredBackendLines[0]).toContain(needle);
    },
  );

  it("only matches a level token that is upper-case in the raw line", async () => {
    // The hook upper-cases the filter but never normalises the line, so a
    // lower-case level token is invisible to the level filter. Pinned as-is:
    // the backend writes upper-case levels (see LEVEL_FIXTURE), and whether
    // lower-case input should also match is a product decision, not a test one.
    getBackendLogs.mockResolvedValue(
      logsResponse("10:00 error lowercase level"),
    );
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setBackendLevel("error");
    });

    expect(result.current.filteredBackendLines).toHaveLength(0);
  });

  // ── text query filtering ────────────────────────────────────────────────

  it("narrows lines by a case-insensitive substring query", async () => {
    getBackendLogs.mockResolvedValue(
      logsResponse("Alpha needle\nbeta other\ngamma"),
    );
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    // Upper-case query against a lower-cased haystack and vice versa.
    act(() => {
      result.current.setBackendQuery("NEEDLE");
    });
    expect(result.current.filteredBackendLines).toEqual(["Alpha needle"]);

    getBackendLogs.mockResolvedValue(logsResponse("alpha NEEDLE\nbeta other"));
    await act(async () => {
      await result.current.loadBackendLogs();
    });
    act(() => {
      result.current.setBackendQuery("needle");
    });
    expect(result.current.filteredBackendLines).toEqual(["alpha NEEDLE"]);
  });

  it("ignores surrounding whitespace in the query", async () => {
    getBackendLogs.mockResolvedValue(logsResponse("Alpha line\nbeta line"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setBackendQuery("   alpha   ");
    });

    expect(result.current.filteredBackendLines).toEqual(["Alpha line"]);
  });

  it("returns nothing when the query matches no line", async () => {
    getBackendLogs.mockResolvedValue(logsResponse("Alpha\nbeta"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setBackendQuery("zzz");
    });

    expect(result.current.filteredBackendLines).toEqual([]);
  });

  it("applies the level filter before the query so both must pass", async () => {
    getBackendLogs.mockResolvedValue(logsResponse(LEVEL_FIXTURE));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setBackendLevel("error");
      result.current.setBackendQuery("disk");
    });

    // The only ERROR line mentions the database, not the disk.
    expect(result.current.filteredBackendLines).toEqual([]);

    act(() => {
      result.current.setBackendQuery("db");
    });
    expect(result.current.filteredBackendLines).toHaveLength(1);
  });

  it("joins the visible lines in newest-first order", async () => {
    // `filteredBackendText` is not part of the hook's return value; the copy
    // action is its only observable consumer, so assert it through there.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    getBackendLogs.mockResolvedValue(logsResponse("one\ntwo\nthree"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      await result.current.handleCopyBackend();
    });

    expect(writeText).toHaveBeenCalledWith("three\ntwo\none");

    act(() => {
      result.current.setBackendNewestFirst(false);
    });

    await act(async () => {
      await result.current.handleCopyBackend();
    });

    expect(writeText).toHaveBeenLastCalledWith("one\ntwo\nthree");
  });

  // ── clipboard ───────────────────────────────────────────────────────────

  it("copies the filtered text and confirms it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    getBackendLogs.mockResolvedValue(logsResponse("keep me\ndrop me"));
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setBackendQuery("keep");
    });

    await act(async () => {
      await result.current.handleCopyBackend();
    });

    expect(writeText).toHaveBeenCalledWith("keep me");
    await act(async () => {
      await result.current.handleCopyBackend("reading snapshot");
    });
    expect(writeText).toHaveBeenLastCalledWith("reading snapshot");
    expect(messageApi.success).toHaveBeenCalled();
    expect(messageApi.error).not.toHaveBeenCalled();
  });

  it("reports a clipboard failure instead of throwing", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    const { result } = renderHook(() => useDebugLogs());

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      await result.current.handleCopyBackend();
    });

    expect(messageApi.error).toHaveBeenCalled();
    expect(messageApi.success).not.toHaveBeenCalled();
  });
});
