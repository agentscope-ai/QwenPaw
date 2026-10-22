import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { portabilityImportApi } from "../../api/modules/import";
import type { ImportJobSnapshot } from "../../api/types/import";
import { useImportJob } from "./useImportJob";

const ACTIVE_JOBS = "qwenpaw.portability.activeImports";

let selectedAgent = "agent-a";

// Every stream attempt is recorded so tests can assert which job was watched
// and whether the abort signal handed to that attempt was cancelled.
type StreamArgs = Parameters<typeof portabilityImportApi.streamEvents>;
let streamCalls: Array<{
  agentId: string;
  jobId: string;
  after: number;
  signal: AbortSignal;
}> = [];
let streamImpl: ((...args: StreamArgs) => Promise<void>) | null = null;

const spies: Array<{ mockRestore: () => void }> = [];

const job = (
  over: Partial<ImportJobSnapshot> = {},
  agentId = "agent-a",
  jobId = `import-${agentId}`,
): ImportJobSnapshot => ({
  job_id: jobId,
  agent_id: agentId,
  state: "awaiting_selection",
  seq: 1,
  providers: [],
  logs: [],
  ...over,
});

const settle = async (ms = 20) => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
};

// Refuse one storage method for the rest of the test; restored in afterEach.
const refuseGet = (target: Storage) =>
  spies.push(
    vi.spyOn(target, "getItem").mockImplementation(() => {
      throw new Error("storage refused");
    }),
  );

const refuseSet = (target: Storage) =>
  spies.push(
    vi.spyOn(target, "setItem").mockImplementation(() => {
      throw new Error("storage refused");
    }),
  );

vi.mock("../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent }),
}));
vi.mock("../../api/modules/import", () => ({
  portabilityImportApi: {
    sources: vi.fn(),
    create: vi.fn(),
    snapshot: vi.fn(),
    start: vi.fn(),
    retry: vi.fn(),
    cancel: vi.fn(),
    current: vi.fn(),
    streamEvents: vi.fn(),
  },
}));

describe("useImportJob event stream", () => {
  beforeEach(() => {
    selectedAgent = "agent-a";
    streamCalls = [];
    streamImpl = null;
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.mocked(portabilityImportApi.current).mockResolvedValue(null);
    vi.mocked(portabilityImportApi.sources).mockResolvedValue([]);
    vi.mocked(portabilityImportApi.create).mockImplementation(async (agentId) =>
      job({}, agentId),
    );
    vi.mocked(portabilityImportApi.snapshot).mockImplementation(
      async (agentId, jobId) => job({}, agentId, jobId),
    );
    vi.mocked(portabilityImportApi.streamEvents).mockImplementation(
      async (agentId, jobId, after, onEvent, signal, onOpen) => {
        streamCalls.push({ agentId, jobId, after, signal });
        if (streamImpl) {
          return streamImpl(agentId, jobId, after, onEvent, signal, onOpen);
        }
        // Default: an open stream that never ends, like a live SSE connection.
        return new Promise<void>(() => undefined);
      },
    );
  });

  afterEach(() => {
    while (spies.length) spies.pop()?.mockRestore();
  });

  it("applies streamed events and stops watching a terminal job", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({}, "agent-a", "job-live"),
    );
    streamImpl = async (_agentId, _jobId, _after, onEvent, _signal, onOpen) => {
      onOpen?.();
      onEvent({
        seq: 2,
        snapshot: job({ state: "completed", seq: 2 }, "agent-a", "job-live"),
      });
    };

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.state).toBe("completed"));
    await settle();

    expect(streamCalls).toHaveLength(1);
    expect(streamCalls[0]).toMatchObject({
      agentId: "agent-a",
      jobId: "job-live",
      after: 1,
    });
    expect(result.current.job?.seq).toBe(2);
    expect(result.current.error).toBe("");
    unmount();
  });

  it("drops stale events and events belonging to another job", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({}, "agent-a", "job-live"),
    );
    streamImpl = async (_agentId, _jobId, _after, onEvent) => {
      // Same seq as the snapshot already on screen: must be ignored.
      onEvent({ seq: 1, snapshot: job({ seq: 1 }, "agent-a", "job-live") });
      // Newer seq but a different job id: must be ignored.
      onEvent({ seq: 2, snapshot: job({ seq: 2 }, "agent-a", "job-other") });
      // Valid event for the watched job.
      onEvent({
        seq: 3,
        snapshot: job(
          { seq: 3, state: "completed", logs: ["done"] },
          "agent-a",
          "job-live",
        ),
      });
    };

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.seq).toBe(3));
    await settle();

    expect(result.current.job?.job_id).toBe("job-live");
    expect(result.current.job?.state).toBe("completed");
    expect(result.current.job?.logs).toEqual(["done"]);
    expect(streamCalls).toHaveLength(1);
    unmount();
  });

  it("surfaces a stream failure and clears it when the stream reopens", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({}, "agent-a", "job-live"),
    );
    let attempt = 0;
    streamImpl = async (_agentId, _jobId, _after, onEvent, _signal, onOpen) => {
      attempt += 1;
      if (attempt === 1) throw new Error("stream broke");
      onOpen?.();
      onEvent({
        seq: 4,
        snapshot: job({ state: "completed", seq: 4 }, "agent-a", "job-live"),
      });
    };

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.error).toBe("stream broke"));
    expect(result.current.job?.state).toBe("awaiting_selection");

    // The watcher backs off for 750ms before reconnecting.
    await waitFor(() => expect(result.current.job?.state).toBe("completed"), {
      timeout: 4000,
    });
    await settle();

    expect(result.current.error).toBe("");
    expect(streamCalls).toHaveLength(2);
    unmount();
  });

  it("polls a snapshot when the stream closes on a non-terminal job", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({}, "agent-a", "job-live"),
    );
    vi.mocked(portabilityImportApi.snapshot).mockResolvedValue(
      job({ seq: 5, state: "completed" }, "agent-a", "job-live"),
    );
    // Stream resolves without delivering anything: the watcher must reconcile.
    streamImpl = async () => undefined;

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.seq).toBe(5), {
      timeout: 4000,
    });
    await settle();

    expect(portabilityImportApi.snapshot).toHaveBeenCalledWith(
      "agent-a",
      "job-live",
    );
    expect(result.current.job?.state).toBe("completed");
    unmount();
  });

  it("does not open a stream for a job that already finished", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({ state: "failed" }, "agent-a", "job-done"),
    );

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.job_id).toBe("job-done"));
    await settle();

    expect(portabilityImportApi.streamEvents).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    unmount();
  });

  it("stops watching when the selected agent changes", async () => {
    // The backend answers per agent; agent-b genuinely has no import job.
    vi.mocked(portabilityImportApi.current).mockImplementation(
      async (agentId) =>
        agentId === "agent-a" ? job({}, agentId, "job-live") : null,
    );

    const { result, rerender, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(streamCalls).toHaveLength(1));

    selectedAgent = "agent-b";
    await act(async () => {
      rerender();
    });
    await settle();

    expect(streamCalls[0].signal.aborted).toBe(true);
    expect(portabilityImportApi.current).toHaveBeenCalledWith("agent-b");
    expect(result.current.job).toBeNull();
    unmount();
  });

  it("reset aborts the watcher and clears the saved job", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({}, "agent-a", "job-live"),
    );

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.job_id).toBe("job-live"));
    expect(JSON.parse(localStorage.getItem(ACTIVE_JOBS) ?? "{}")).toEqual({
      "agent-a": "job-live",
    });

    act(() => result.current.reset());
    await settle();

    expect(streamCalls[0].signal.aborted).toBe(true);
    expect(result.current.job).toBeNull();
    expect(result.current.error).toBe("");
    expect(JSON.parse(localStorage.getItem(ACTIVE_JOBS) ?? "{}")).toEqual({});
    unmount();
  });

  it("shows a freshly scanned job once the previous one was reset", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({}, "agent-a", "job-live"),
    );

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(streamCalls).toHaveLength(1));

    act(() => result.current.reset());
    await act(() => result.current.scan(["codex"]));

    expect(streamCalls).toHaveLength(2);
    expect(streamCalls[0].signal.aborted).toBe(true);
    expect(streamCalls[1].signal.aborted).toBe(false);
    expect(streamCalls[1].jobId).toBe("import-agent-a");
    expect(result.current.job?.job_id).toBe("import-agent-a");
    expect(result.current.loading).toBe(false);
    unmount();
  });
});

describe("useImportJob command failures", () => {
  beforeEach(() => {
    selectedAgent = "agent-a";
    streamCalls = [];
    streamImpl = null;
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.mocked(portabilityImportApi.current).mockResolvedValue(null);
    vi.mocked(portabilityImportApi.sources).mockResolvedValue([]);
    vi.mocked(portabilityImportApi.create).mockImplementation(async (agentId) =>
      job({}, agentId),
    );
    vi.mocked(portabilityImportApi.snapshot).mockImplementation(
      async (agentId, jobId) => job({}, agentId, jobId),
    );
    vi.mocked(portabilityImportApi.streamEvents).mockImplementation(
      async () => new Promise<void>(() => undefined),
    );
  });

  afterEach(() => {
    while (spies.length) spies.pop()?.mockRestore();
  });

  it("rejects start, retry and cancel when no job exists", async () => {
    const { result, unmount } = renderHook(() => useImportJob());
    await settle();

    const expected = "Import job has not been created";
    await act(async () => {
      await expect(
        result.current.start({ codex: { sessions: true } }),
      ).rejects.toThrow(expected);
      await expect(
        result.current.retry({ codex: { sessions: true } }),
      ).rejects.toThrow(expected);
      await expect(result.current.cancel()).rejects.toThrow(expected);
    });

    expect(portabilityImportApi.start).not.toHaveBeenCalled();
    expect(portabilityImportApi.retry).not.toHaveBeenCalled();
    expect(portabilityImportApi.cancel).not.toHaveBeenCalled();
    unmount();
  });

  it("reports a failed start without losing the job", async () => {
    vi.mocked(portabilityImportApi.start).mockRejectedValue(
      new Error("start refused"),
    );

    const { result, unmount } = renderHook(() => useImportJob());
    await act(() => result.current.scan(["codex"]));
    await act(async () => {
      await expect(
        result.current.start({ codex: { sessions: true } }, true),
      ).rejects.toThrow("start refused");
    });

    expect(portabilityImportApi.start).toHaveBeenCalledWith(
      "agent-a",
      "import-agent-a",
      { codex: { sessions: true } },
      true,
    );
    expect(result.current.error).toBe("start refused");
    expect(result.current.loading).toBe(false);
    expect(result.current.job?.job_id).toBe("import-agent-a");
    unmount();
  });

  it("stringifies a non-Error rejection from cancel", async () => {
    vi.mocked(portabilityImportApi.cancel).mockRejectedValue("plain reason");

    const { result, unmount } = renderHook(() => useImportJob());
    await act(() => result.current.scan(["codex"]));
    await act(async () => {
      await expect(result.current.cancel()).rejects.toBe("plain reason");
    });

    expect(result.current.error).toBe("plain reason");
    expect(result.current.loading).toBe(false);
    unmount();
  });

  it("reports a failed retry and keeps the previous snapshot", async () => {
    vi.mocked(portabilityImportApi.retry).mockRejectedValue(
      new Error("retry refused"),
    );

    const { result, unmount } = renderHook(() => useImportJob());
    await act(() => result.current.scan(["codex"]));
    await act(async () => {
      await expect(
        result.current.retry({ qoder: { sessions: false } }),
      ).rejects.toThrow("retry refused");
    });

    expect(result.current.error).toBe("retry refused");
    expect(result.current.job?.job_id).toBe("import-agent-a");
    unmount();
  });

  it("reports a failed scan", async () => {
    vi.mocked(portabilityImportApi.create).mockRejectedValue(
      new Error("cannot create"),
    );

    const { result, unmount } = renderHook(() => useImportJob());
    await act(async () => {
      await expect(result.current.scan(["codex"])).rejects.toThrow(
        "cannot create",
      );
    });

    expect(result.current.error).toBe("cannot create");
    expect(result.current.loading).toBe(false);
    expect(result.current.job).toBeNull();
    unmount();
  });
});

describe("useImportJob source detection", () => {
  beforeEach(() => {
    selectedAgent = "agent-a";
    streamCalls = [];
    streamImpl = null;
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.mocked(portabilityImportApi.current).mockResolvedValue(null);
    vi.mocked(portabilityImportApi.sources).mockResolvedValue([]);
    vi.mocked(portabilityImportApi.create).mockImplementation(async (agentId) =>
      job({}, agentId),
    );
    vi.mocked(portabilityImportApi.snapshot).mockImplementation(
      async (agentId, jobId) => job({}, agentId, jobId),
    );
    vi.mocked(portabilityImportApi.streamEvents).mockImplementation(
      async () => new Promise<void>(() => undefined),
    );
  });

  afterEach(() => {
    while (spies.length) spies.pop()?.mockRestore();
  });

  it("lists import sources while idle and reports probe failures", async () => {
    vi.mocked(portabilityImportApi.sources).mockResolvedValueOnce([
      { source: "codex", name: "Codex", detected: true },
    ]);

    const { result, unmount } = renderHook(() => useImportJob());
    await settle();

    const found = await act(() => result.current.detect());

    expect(found).toEqual([{ source: "codex", name: "Codex", detected: true }]);
    expect(result.current.sources).toHaveLength(1);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe("");

    vi.mocked(portabilityImportApi.sources).mockRejectedValue(
      new Error("probe failed"),
    );
    await act(async () => {
      await expect(result.current.detect()).rejects.toThrow("probe failed");
    });

    expect(result.current.error).toBe("probe failed");
    expect(result.current.loading).toBe(false);
    unmount();
  });

  it("keeps loading and error untouched while a job is visible", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({ state: "failed" }, "agent-a", "job-done"),
    );
    vi.mocked(portabilityImportApi.sources).mockRejectedValue(
      new Error("probe failed"),
    );

    const { result, unmount } = renderHook(() => useImportJob());
    await waitFor(() => expect(result.current.job?.job_id).toBe("job-done"));

    await act(async () => {
      await expect(result.current.detect()).rejects.toThrow("probe failed");
    });

    // A visible job means detect() is not the idle probe: it must not blank
    // the job error surface or flip the page into a loading state.
    expect(result.current.error).toBe("");
    expect(result.current.loading).toBe(false);
    expect(result.current.sources).toEqual([]);
    unmount();
  });
});

describe("useImportJob storage recovery", () => {
  beforeEach(() => {
    selectedAgent = "agent-a";
    streamCalls = [];
    streamImpl = null;
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.mocked(portabilityImportApi.current).mockResolvedValue(null);
    vi.mocked(portabilityImportApi.sources).mockResolvedValue([]);
    vi.mocked(portabilityImportApi.create).mockImplementation(async (agentId) =>
      job({}, agentId),
    );
    vi.mocked(portabilityImportApi.snapshot).mockImplementation(
      async (agentId, jobId) => job({}, agentId, jobId),
    );
    vi.mocked(portabilityImportApi.streamEvents).mockImplementation(
      async () => new Promise<void>(() => undefined),
    );
  });

  afterEach(() => {
    while (spies.length) spies.pop()?.mockRestore();
  });

  it("reads the saved job from session storage when local storage throws", async () => {
    sessionStorage.setItem(
      ACTIVE_JOBS,
      JSON.stringify({ "agent-a": "job-sess" }),
    );
    refuseGet(localStorage);

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.job_id).toBe("job-sess"));
    expect(portabilityImportApi.snapshot).toHaveBeenCalledWith(
      "agent-a",
      "job-sess",
    );
    unmount();
  });

  it("ignores malformed local storage payloads", async () => {
    localStorage.setItem(ACTIVE_JOBS, "not-json");

    const { result, unmount } = renderHook(() => useImportJob());
    await settle();

    expect(portabilityImportApi.snapshot).not.toHaveBeenCalled();
    expect(portabilityImportApi.current).toHaveBeenCalledWith("agent-a");
    expect(result.current.job).toBeNull();
    unmount();
  });

  it("ignores a storage payload that is not a plain object", async () => {
    localStorage.setItem(ACTIVE_JOBS, JSON.stringify(["agent-a"]));

    const { result, unmount } = renderHook(() => useImportJob());
    await settle();

    expect(portabilityImportApi.snapshot).not.toHaveBeenCalled();
    expect(portabilityImportApi.current).toHaveBeenCalledWith("agent-a");
    expect(result.current.job).toBeNull();
    unmount();
  });

  it("drops storage entries whose job id is not a string", async () => {
    sessionStorage.setItem(
      ACTIVE_JOBS,
      JSON.stringify({ "agent-a": 42, "agent-b": "job-b" }),
    );

    const { result, unmount } = renderHook(() => useImportJob());
    await settle();

    expect(portabilityImportApi.snapshot).not.toHaveBeenCalled();
    expect(portabilityImportApi.current).toHaveBeenCalledWith("agent-a");
    expect(result.current.job).toBeNull();
    unmount();
  });

  it("falls back to the current job when the saved one is gone", async () => {
    sessionStorage.setItem(
      ACTIVE_JOBS,
      JSON.stringify({ "agent-a": "job-gone" }),
    );
    vi.mocked(portabilityImportApi.snapshot).mockRejectedValue(
      new Error("job not found"),
    );
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({ state: "failed" }, "agent-a", "import-current"),
    );

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() =>
      expect(result.current.job?.job_id).toBe("import-current"),
    );
    expect(result.current.error).toBe("");
    expect(JSON.parse(localStorage.getItem(ACTIVE_JOBS) ?? "{}")).toEqual({
      "agent-a": "import-current",
    });
    unmount();
  });

  it("clears storage and reports an error when no job can be restored", async () => {
    sessionStorage.setItem(
      ACTIVE_JOBS,
      JSON.stringify({ "agent-a": "job-gone" }),
    );
    vi.mocked(portabilityImportApi.snapshot).mockRejectedValue(
      new Error("job not found"),
    );
    vi.mocked(portabilityImportApi.current).mockRejectedValue(
      new Error("backend down"),
    );

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.error).toBe("backend down"));

    expect(result.current.job).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(JSON.parse(localStorage.getItem(ACTIVE_JOBS) ?? "{}")).toEqual({});
    unmount();
  });

  it("writes the recovered job to session storage when local storage refuses", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({ state: "failed" }, "agent-a", "import-current"),
    );
    refuseSet(localStorage);

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() =>
      expect(result.current.job?.job_id).toBe("import-current"),
    );
    expect(sessionStorage.getItem(ACTIVE_JOBS)).toBe(
      JSON.stringify({ "agent-a": "import-current" }),
    );
    unmount();
  });

  it("keeps working when both storage layers refuse writes", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job({ state: "failed" }, "agent-a", "import-current"),
    );
    refuseSet(localStorage);
    refuseSet(Storage.prototype);

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() =>
      expect(result.current.job?.job_id).toBe("import-current"),
    );
    expect(result.current.error).toBe("");
    unmount();
  });

  it("prefers the session storage entry over the local storage one", async () => {
    localStorage.setItem(
      ACTIVE_JOBS,
      JSON.stringify({ "agent-a": "job-local" }),
    );
    sessionStorage.setItem(
      ACTIVE_JOBS,
      JSON.stringify({ "agent-a": "job-session" }),
    );

    const { result, unmount } = renderHook(() => useImportJob());

    await waitFor(() => expect(result.current.job?.job_id).toBe("job-session"));
    expect(portabilityImportApi.snapshot).toHaveBeenCalledWith(
      "agent-a",
      "job-session",
    );
    unmount();
  });
});
