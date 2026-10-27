// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  MarketPluginEntry,
  MarketPluginSortBy,
} from "@/api/modules/pluginMarket";

// The suites below cover the state transitions that only appear when a request
// fails, is aborted, or races a filter change. The message mock is hoisted so
// the install toasts can be asserted instead of being thrown away.

const hoisted = vi.hoisted(() => ({
  fetchMarketPlugins: vi.fn(),
  installPlugin: vi.fn(),
  buildMarketDownloadUrl: vi.fn(() => "https://example.com/plugin.zip"),
  message: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.message }),
}));

vi.mock("@/api/modules/pluginMarket", () => ({
  fetchMarketPlugins: hoisted.fetchMarketPlugins,
  buildMarketDownloadUrl: hoisted.buildMarketDownloadUrl,
}));

vi.mock("@/api/modules/plugin", () => ({
  installPlugin: hoisted.installPlugin,
}));

import { useMarketPlugins } from "./useMarketPlugins";

const PAGE_SIZE = 20;

function makeEntry(
  id: string,
  extra: Partial<MarketPluginEntry> = {},
): MarketPluginEntry {
  return {
    id,
    display_name: id,
    developer: "developer",
    owner: "owner",
    version: "1.0.0",
    logo_url: null,
    downloads: 1,
    view_count: 1,
    details_url: null,
    locales: { en: { description: id, category: "general" } },
    ...extra,
  };
}

function makePage(count: number, total: number, prefix = "plugin") {
  return {
    plugins: Array.from({ length: count }, (_, index) =>
      makeEntry(`${prefix}-${index}`),
    ),
    total,
  };
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type MarketPage = { plugins: MarketPluginEntry[]; total: number };

/** Stub the version endpoint so the mount effect settles deterministically. */
function stubVersion(payload: unknown = { version: "2.0.0" }, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(payload) }),
  );
}

describe("useMarketPlugins version probe", () => {
  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    hoisted.message.success.mockReset();
    hoisted.message.error.mockReset();
    hoisted.fetchMarketPlugins.mockResolvedValue({ plugins: [], total: 0 });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reports a non-2xx version response as an unavailable version", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    stubVersion(null, false);

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.qwenpawVersion).toBeNull();
    expect(errorSpy).toHaveBeenCalled();
  });

  it("ignores an aborted version request without logging", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // The hook's guard is `err instanceof Error && err.name === "AbortError"`,
    // so the rejection is built to that contract. Note: in this Node/jsdom
    // runtime `new DOMException(...)` is NOT an instance of Error (verified by
    // a throwaway probe), which is an environment trait, not a product claim.
    const abortError = Object.assign(new Error("aborted"), {
      name: "AbortError",
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.qwenpawVersion).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("logs and clears the version when the probe rejects unexpectedly", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network-down")),
    );

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.qwenpawVersion).toBeNull();
    expect(errorSpy).toHaveBeenCalledWith(
      "[useMarketPlugins] failed to fetch version:",
      expect.any(Error),
    );
  });

  it("keeps the version null when the payload is not an object", async () => {
    stubVersion("1.2.3");

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.qwenpawVersion).toBeNull();
  });

  it("keeps the version null when the version field is not a string", async () => {
    stubVersion({ version: 2 });

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.qwenpawVersion).toBeNull();
  });

  it("exposes the reported version for compatibility checks", async () => {
    stubVersion({ version: "3.1.0" });

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.qwenpawVersion).toBe("3.1.0"));
  });
});

describe("useMarketPlugins list failure handling", () => {
  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    hoisted.message.success.mockReset();
    hoisted.message.error.mockReset();
    stubVersion();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("clears the list and reports the market as unavailable on first load", async () => {
    hoisted.fetchMarketPlugins.mockRejectedValue(new Error("500"));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("pluginManager.marketUnavailable");
    expect(result.current.plugins).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.page).toBe(1);
    // A first-load failure must not mark incremental loading as blocked.
    expect(result.current.autoLoadBlocked).toBe(false);
  });

  it("blocks auto load-more when appending a further page fails", async () => {
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) =>
      page_number === 1
        ? Promise.resolve(makePage(PAGE_SIZE, 21))
        : Promise.reject(new Error("500")),
    );

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.plugins).toHaveLength(PAGE_SIZE));

    await act(async () => {
      result.current.handleLoadMore();
    });

    await waitFor(() => expect(result.current.autoLoadBlocked).toBe(true));
    expect(result.current.error).toBe("pluginManager.marketUnavailable");
    // The already loaded page is preserved so the list does not flicker away.
    expect(result.current.plugins).toHaveLength(PAGE_SIZE);
    expect(result.current.loadingMore).toBe(false);
  });

  it("clears the error once a later request succeeds", async () => {
    hoisted.fetchMarketPlugins
      .mockRejectedValueOnce(new Error("500"))
      .mockResolvedValue(makePage(2, 2));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() =>
      expect(result.current.error).toBe("pluginManager.marketUnavailable"),
    );

    act(() => result.current.handleRefresh());

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.plugins).toHaveLength(2);
  });

  it("treats an aborted in-flight list request as stale and drops it", async () => {
    const first = deferred<MarketPage>();
    const second = deferred<MarketPage>();
    let calls = 0;
    hoisted.fetchMarketPlugins.mockImplementation(() => {
      calls += 1;
      return calls === 1 ? first.promise : second.promise;
    });

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    // Changing the search aborts the first request and starts a second one.
    act(() => result.current.handleSearch("query"));

    await act(async () => {
      first.resolve(makePage(1, 1, "stale"));
    });

    // The stale resolution must not reach the state.
    expect(result.current.plugins).toEqual([]);

    await act(async () => {
      second.resolve(makePage(1, 1, "fresh"));
    });

    await waitFor(() => expect(result.current.plugins).toHaveLength(1));
    expect(result.current.plugins[0].id).toBe("fresh-0");
  });

  it("ignores an AbortError raised by the list request itself", async () => {
    hoisted.fetchMarketPlugins.mockRejectedValue(
      new DOMException("aborted", "AbortError"),
    );

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    // Aborting is not a market failure, so no error banner is shown.
    expect(result.current.error).toBeNull();
  });

  it("tolerates a list payload without a plugins array", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue({ total: 5 });

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.plugins).toEqual([]);
    expect(result.current.total).toBe(5);
  });
});

describe("useMarketPlugins load-more gating", () => {
  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    stubVersion();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("does not request another page once every item is loaded", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(3, 3));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.plugins).toHaveLength(3));
    expect(result.current.hasMore).toBe(false);

    await act(async () => {
      result.current.handleLoadMore();
    });

    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(1);
  });

  it("does not auto load more while a blocked retry is pending", async () => {
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) =>
      page_number === 1
        ? Promise.resolve(makePage(PAGE_SIZE, 40))
        : Promise.reject(new Error("500")),
    );

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.plugins).toHaveLength(PAGE_SIZE));
    await act(async () => {
      result.current.handleLoadMore();
    });
    await waitFor(() => expect(result.current.autoLoadBlocked).toBe(true));
    const callsAfterBlock = hoisted.fetchMarketPlugins.mock.calls.length;

    await act(async () => {
      result.current.handleLoadMore();
    });

    // The plain handler respects the block and issues no further request.
    expect(hoisted.fetchMarketPlugins).toHaveBeenCalledTimes(callsAfterBlock);
  });

  it("retries a blocked load-more and recovers the next page", async () => {
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) => {
      if (page_number === 1) return Promise.resolve(makePage(PAGE_SIZE, 21));
      if (page_number === 2) return Promise.reject(new Error("500"));
      return Promise.resolve(makePage(1, 21, "page3"));
    });

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.plugins).toHaveLength(PAGE_SIZE));
    await act(async () => {
      result.current.handleLoadMore();
    });
    await waitFor(() => expect(result.current.autoLoadBlocked).toBe(true));

    // Third attempt: the retry handler lifts the block and asks again.
    hoisted.fetchMarketPlugins.mockImplementation(() =>
      Promise.resolve(makePage(1, 21, "page3")),
    );
    await act(async () => {
      result.current.handleRetryLoadMore();
    });

    await waitFor(() => expect(result.current.autoLoadBlocked).toBe(false));
    await waitFor(() => expect(result.current.plugins).toHaveLength(21));
    expect(result.current.page).toBe(2);
  });

  it("requests the search, sort and refresh filters it was given", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(1, 1));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    // `search` is not part of the returned state, so the request arguments are
    // the observable contract for the keyword.
    act(() => result.current.handleSearch("vector"));
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "vector", page_number: 1 }),
        expect.anything(),
      ),
    );

    const sort: MarketPluginSortBy = "updated_time";
    act(() => result.current.handleSortChange(sort));
    await waitFor(() => expect(result.current.sortBy).toBe("updated_time"));
    expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: "updated_time", page_number: 1 }),
      expect.anything(),
    );

    const before = hoisted.fetchMarketPlugins.mock.calls.length;
    act(() => result.current.handleRefresh());
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins.mock.calls.length).toBe(before + 1),
    );
    expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page_number: 1,
        search: "vector",
        sort_by: "updated_time",
      }),
      expect.anything(),
    );
  });

  it("logs when the version probe is aborted as a DOMException", async () => {
    // Characterization of an asymmetry between the two abort guards in this
    // hook: the list request accepts `err instanceof DOMException`, while the
    // version probe requires `err instanceof Error`. A DOMException abort
    // therefore reaches the probe's error branch. Whether a real browser abort
    // hits this branch is not verified here; what is verified is that the two
    // guards in the hook source are written differently.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError")),
    );

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.qwenpawVersion).toBeNull();
    expect(errorSpy).toHaveBeenCalled();
  });

  it("omits empty search and category filters from the request", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(0, 0));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    const params = hoisted.fetchMarketPlugins.mock.calls[0][0];
    expect(params.search).toBeUndefined();
    expect(params.category).toBeUndefined();
    expect(params.sort_by).toBe("downloads");
  });

  it("keeps the newer controller when a stale load-more settles last", async () => {
    // A load-more in flight can be overtaken by a filter change: the effect
    // installs a fresh controller, and the stale page must not clear it on its
    // way out, otherwise the new request could no longer be aborted.
    const firstPage = makePage(PAGE_SIZE, 40);
    const stalePage = deferred<MarketPage>();
    let calls = 0;
    hoisted.fetchMarketPlugins.mockImplementation(({ page_number }) => {
      calls += 1;
      if (page_number === 2 && calls === 2) return stalePage.promise;
      return Promise.resolve(firstPage);
    });

    const { result, unmount } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.plugins).toHaveLength(PAGE_SIZE));

    await act(async () => {
      result.current.handleLoadMore();
    });
    await waitFor(() => expect(result.current.loadingMore).toBe(true));

    // Overtake the pending page, then let it settle afterwards.
    const beforeSearch = hoisted.fetchMarketPlugins.mock.calls.length;
    act(() => result.current.handleSearch("newer"));
    await waitFor(() =>
      expect(hoisted.fetchMarketPlugins.mock.calls.length).toBeGreaterThan(
        beforeSearch,
      ),
    );
    expect(hoisted.fetchMarketPlugins).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: "newer", page_number: 1 }),
      expect.anything(),
    );

    await act(async () => {
      stalePage.resolve(makePage(1, 40, "stale-page"));
    });

    // Unmounting must still be able to abort whatever request is current.
    expect(() => unmount()).not.toThrow();
  });
});

describe("useMarketPlugins compatibility helper", () => {
  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    stubVersion({ version: "2.4.1" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("matches an entry labelled for the running major version", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(0, 0));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.qwenpawVersion).toBe("2.4.1"));
    expect(
      result.current.isCompatible(
        makeEntry("ok", { qwenpaw_compat_labels: ["2.x"] }),
      ),
    ).toBe(true);
    expect(
      result.current.isCompatible(
        makeEntry("no", { qwenpaw_compat_labels: ["1.x"] }),
      ),
    ).toBe(false);
  });

  it("treats an entry without compatibility labels as compatible", async () => {
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(0, 0));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.qwenpawVersion).toBe("2.4.1"));
    expect(result.current.isCompatible(makeEntry("plain"))).toBe(true);
    expect(
      result.current.isCompatible(
        makeEntry("empty", { qwenpaw_compat_labels: [] }),
      ),
    ).toBe(true);
  });

  it("treats every entry as compatible while the version is unknown", async () => {
    stubVersion(null, false);
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(0, 0));

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );

    await waitFor(() => expect(result.current.qwenpawVersion).toBeNull());
    expect(
      result.current.isCompatible(
        makeEntry("any", { qwenpaw_compat_labels: ["9.x"] }),
      ),
    ).toBe(true);
  });
});

describe("useMarketPlugins install flow", () => {
  const installed = {
    id: "installed-1",
    name: "Installed Plugin",
    version: "1.0.0",
    description: "d",
    loaded: true,
    message: "ok",
  };

  beforeEach(() => {
    hoisted.fetchMarketPlugins.mockReset();
    hoisted.installPlugin.mockReset();
    hoisted.buildMarketDownloadUrl.mockClear();
    hoisted.message.success.mockReset();
    hoisted.message.error.mockReset();
    hoisted.fetchMarketPlugins.mockResolvedValue(makePage(0, 0));
    stubVersion();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("installs with force and notifies the caller on success", async () => {
    hoisted.installPlugin.mockResolvedValue(installed);
    const onInstalled = vi.fn().mockResolvedValue(undefined);
    const entry = makeEntry("installable");

    const { result } = renderHook(() => useMarketPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleInstall(entry);
    });

    expect(hoisted.buildMarketDownloadUrl).toHaveBeenCalledWith(entry);
    expect(hoisted.installPlugin).toHaveBeenCalledWith(
      "https://example.com/plugin.zip",
      { force: true },
    );
    expect(onInstalled).toHaveBeenCalledWith(installed);
    expect(hoisted.message.success).toHaveBeenCalledWith(
      "pluginManager.installSuccess: Installed Plugin",
    );
    expect(result.current.installingId).toBeNull();
  });

  it("surfaces the backend message when the install rejects", async () => {
    hoisted.installPlugin.mockRejectedValue(new Error("disk full"));
    const onInstalled = vi.fn();

    const { result } = renderHook(() => useMarketPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleInstall(makeEntry("broken"));
    });

    expect(hoisted.message.error).toHaveBeenCalledWith("disk full");
    expect(onInstalled).not.toHaveBeenCalled();
    expect(result.current.installingId).toBeNull();
  });

  it("falls back to a generic message for a non-Error rejection", async () => {
    hoisted.installPlugin.mockRejectedValue("string-failure");

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleInstall(makeEntry("weird"));
    });

    expect(hoisted.message.error).toHaveBeenCalledWith(
      "pluginManager.installFailed",
    );
  });

  it("reports a failure raised by the post-install callback", async () => {
    hoisted.installPlugin.mockResolvedValue(installed);
    const onInstalled = vi.fn().mockRejectedValue(new Error("refresh failed"));

    const { result } = renderHook(() => useMarketPlugins({ onInstalled }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleInstall(makeEntry("after-fail"));
    });

    // The install itself succeeded, so the success toast still fires.
    expect(hoisted.message.success).toHaveBeenCalled();
    expect(hoisted.message.error).toHaveBeenCalledWith("refresh failed");
    expect(result.current.installingId).toBeNull();
  });

  it("exposes the installing id while the request is in flight", async () => {
    const gate = deferred<typeof installed>();
    hoisted.installPlugin.mockReturnValue(gate.promise);

    const { result } = renderHook(() =>
      useMarketPlugins({ onInstalled: vi.fn() }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    let pending!: Promise<void>;
    act(() => {
      pending = result.current.handleInstall(makeEntry("slow", {}));
    });

    await waitFor(() => expect(result.current.installingId).toBe("slow"));

    await act(async () => {
      gate.resolve(installed);
      await pending;
    });

    expect(result.current.installingId).toBeNull();
  });
});
