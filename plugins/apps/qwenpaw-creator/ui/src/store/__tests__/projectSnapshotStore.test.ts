import { afterEach, describe, expect, it, vi } from "vitest";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";

function response(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: new Headers(headers),
    json: vi.fn(async () => body),
  } as unknown as Response;
}

function project(generation: number, name = `Project ${generation}`) {
  return {
    schema_version: 1,
    project_id: "p1",
    generation,
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
    name,
    description: "",
    scenario: "general",
    settings: {},
    strategy: {},
    sources: {},
    visual: {},
    story: {},
    production: {},
    post_production: {},
    assets: {},
  };
}

function snapshot(generation: number, name?: string): Response {
  return response(
    200,
    {
      projectId: "p1",
      generation,
      etag: `sha256:g${generation}`,
      syncStatus: "healthy",
      project: project(generation, name),
    },
    { ETag: `"sha256:g${generation}"` },
  );
}

afterEach(() => {
  useProjectSnapshotStore.getState().reset();
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

    await useProjectSnapshotStore.getState().pollOnce("p1");
    const lastGood = useProjectSnapshotStore.getState().project;
    await useProjectSnapshotStore.getState().pollOnce("p1");

    const state = useProjectSnapshotStore.getState();
    expect(state.project).toBe(lastGood);
    expect(state.project?.name).toBe("Last good");
    expect(state.generation).toBe(3);
    expect(state.syncStatus).toBe("invalid");
    expect(state.syncError).toBe("project.json is invalid");
    expect(
      new Headers(fetchMock.mock.calls[1][1].headers).get("If-None-Match"),
    ).toBe('"sha256:g3"');
  });

  it("deduplicates concurrent polls for the same Project", async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const first = useProjectSnapshotStore.getState().pollOnce("p1");
    const second = useProjectSnapshotStore.getState().pollOnce("p1");
    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveFetch(snapshot(1));
    await Promise.all([first, second]);
    expect(useProjectSnapshotStore.getState().generation).toBe(1);
  });

  it("never replaces a higher generation with a later low-generation response", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(snapshot(5, "Current"))
        .mockResolvedValueOnce(snapshot(4, "Stale")),
    );

    await useProjectSnapshotStore.getState().pollOnce("p1");
    await useProjectSnapshotStore.getState().pollOnce("p1");

    const state = useProjectSnapshotStore.getState();
    expect(state.generation).toBe(5);
    expect(state.project?.name).toBe("Current");
    expect(state.appliedRequestSequence).toBe(state.issuedRequestSequence);
  });

  it("evicts the last-good snapshot and stops polling after Project deletion", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(snapshot(2, "Before deletion"))
      .mockResolvedValueOnce(
        response(404, {
          code: "NOT_FOUND",
          message: "Project 不存在",
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const stop = useProjectSnapshotStore.getState().startPolling("p1", {
      activeIntervalMs: 100,
      hiddenIntervalMs: 1_000,
      retryBaseMs: 50,
      maxBackoffMs: 200,
      jitterRatio: 0,
      random: () => 0.5,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(useProjectSnapshotStore.getState().project?.name).toBe(
      "Before deletion",
    );

    await vi.advanceTimersByTimeAsync(100);
    const state = useProjectSnapshotStore.getState();
    expect(state.project).toBeNull();
    expect(state.generation).toBeNull();
    expect(state.etag).toBeNull();
    expect(state.syncStatus).toBe("not_found");
    expect(state.polling).toBe(false);

    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
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

    const stop = useProjectSnapshotStore.getState().startPolling("p1", {
      activeIntervalMs: 100,
      hiddenIntervalMs: 1_000,
      retryBaseMs: 50,
      maxBackoffMs: 200,
      jitterRatio: 0,
      random: () => 0.5,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(99);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);

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

    const stop = useProjectSnapshotStore.getState().startPolling("p1", {
      activeIntervalMs: 1_000,
      hiddenIntervalMs: 2_000,
      retryBaseMs: 100,
      maxBackoffMs: 250,
      jitterRatio: 0,
      random: () => 0.5,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(249);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    stop();
  });
});
