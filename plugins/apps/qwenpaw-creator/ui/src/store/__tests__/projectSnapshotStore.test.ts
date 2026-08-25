import { afterEach, describe, expect, it, vi } from "vitest";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import {
  jsonResponse as response,
  snapshotResponse as snapshot,
} from "@/test/projectSnapshotFixtures";

const store = () => useProjectSnapshotStore.getState();
const poll = () => store().pollOnce("p1");
const startPolling = (overrides: Record<string, number> = {}) =>
  store().startPolling("p1", {
    activeIntervalMs: 100,
    hiddenIntervalMs: 1_000,
    retryBaseMs: 50,
    maxBackoffMs: 200,
    jitterRatio: 0,
    random: () => 0.5,
    ...overrides,
  });

/** Advance fake timers step by step, asserting the fetch call count. */
async function ticks(mock: unknown, steps: Array<[number, number]>) {
  for (const [ms, calls] of steps) {
    await vi.advanceTimersByTimeAsync(ms);
    expect(mock).toHaveBeenCalledTimes(calls);
  }
}

afterEach(() => {
  store().reset();
  vi.useRealTimers();
});

describe("Project snapshot authority store", () => {
  it("retains the last-good Project when a later file snapshot is invalid", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(snapshot(3, "Last good"))
      .mockResolvedValueOnce(
        response(409, {
          code: "PROJECT_INVALID",
          syncStatus: "invalid",
          lastGoodGeneration: 3,
          message: "project.json is invalid",
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await poll();
    const lastGood = store().project;
    await poll();
    expect(store().project).toBe(lastGood);
    expect(store()).toMatchObject({
      generation: 3,
      syncStatus: "invalid",
      syncError: "project.json is invalid",
    });
    expect(
      new Headers(fetchMock.mock.calls[1][1].headers).get("If-None-Match"),
    ).toBe('"sha256:g3"');
  });

  it("deduplicates concurrent polls and rejects a later low-generation response", async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const first = poll();
    const second = poll();
    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveFetch(snapshot(5, "Current"));
    await Promise.all([first, second]);
    expect(store().generation).toBe(5);

    const third = poll();
    resolveFetch(snapshot(4, "Stale"));
    await third;
    expect(store().generation).toBe(5);
    expect(store().project?.name).toBe("Current");
    expect(store().appliedRequestSequence).toBe(store().issuedRequestSequence);
  });

  it("evicts the last-good snapshot and stops polling after Project deletion", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(snapshot(2, "Before deletion"))
      .mockResolvedValueOnce(
        response(404, { code: "NOT_FOUND", message: "Project 不存在" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const stop = startPolling();
    await vi.advanceTimersByTimeAsync(0);
    expect(store().project?.name).toBe("Before deletion");

    await vi.advanceTimersByTimeAsync(100);
    expect(store()).toMatchObject({
      project: null,
      generation: null,
      etag: null,
      syncStatus: "not_found",
      polling: false,
    });
    await ticks(fetchMock, [[1_000, 2]]);
    stop();
  });

  it("uses active and hidden intervals without overlapping requests", async () => {
    vi.useFakeTimers();
    const originalVisibility = Object.getOwnPropertyDescriptor(
      document,
      "visibilityState",
    );
    let visibility: DocumentVisibilityState = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });
    const fetchMock = vi.fn(async () => snapshot(1));
    vi.stubGlobal("fetch", fetchMock);

    const stop = startPolling();
    await ticks(fetchMock, [
      [0, 1],
      [99, 1],
      [1, 2],
    ]);
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    await ticks(fetchMock, [
      [999, 2],
      [1, 3],
    ]);

    stop();
    if (originalVisibility)
      Object.defineProperty(document, "visibilityState", originalVisibility);
  });

  it("caps exponential retry delay after poll failures", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => {
      throw new Error("offline");
    });
    vi.stubGlobal("fetch", fetchMock);

    const stop = startPolling({ retryBaseMs: 100, maxBackoffMs: 250 });
    await ticks(fetchMock, [
      [0, 1],
      [100, 2],
      [200, 3],
      [249, 3],
      [1, 4],
    ]);
    stop();
  });
});
