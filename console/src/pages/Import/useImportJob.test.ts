import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { portabilityImportApi } from "../../api/modules/import";
import { useImportJob } from "./useImportJob";

let selectedAgent = "agent-a";

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

const job = (agentId: string, jobId = `import-${agentId}`) => ({
  job_id: jobId,
  agent_id: agentId,
  state: "awaiting_selection" as const,
  seq: 1,
  providers: [],
  logs: [],
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}

describe("useImportJob", () => {
  beforeEach(() => {
    selectedAgent = "agent-a";
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    vi.mocked(portabilityImportApi.create).mockImplementation(async (agentId) =>
      job(agentId),
    );
    vi.mocked(portabilityImportApi.snapshot).mockImplementation(
      async (agentId, jobId) => job(agentId, jobId),
    );
    vi.mocked(portabilityImportApi.start).mockImplementation(
      async (agentId, jobId) => ({ ...job(agentId, jobId), state: "running" }),
    );
    vi.mocked(portabilityImportApi.cancel).mockImplementation(
      async (agentId, jobId) => ({
        ...job(agentId, jobId),
        seq: 2,
        state: "interrupted",
      }),
    );
    vi.mocked(portabilityImportApi.current).mockResolvedValue(null);
    vi.mocked(portabilityImportApi.sources).mockResolvedValue([]);
    vi.mocked(portabilityImportApi.streamEvents).mockReturnValue(
      new Promise(() => undefined),
    );
  });

  it("recovers the current job when browser storage is empty", async () => {
    vi.mocked(portabilityImportApi.current).mockResolvedValue(
      job("agent-a", "import-current"),
    );
    const { result } = renderHook(() => useImportJob());

    await waitFor(() =>
      expect(result.current.job?.job_id).toBe("import-current"),
    );
  });

  it("clears an unavailable saved job so a new import can take over", async () => {
    sessionStorage.setItem(
      "qwenpaw.portability.activeImports",
      JSON.stringify({ "agent-a": "missing-job" }),
    );
    vi.mocked(portabilityImportApi.snapshot).mockRejectedValueOnce(
      new Error("import job not found"),
    );
    const { result } = renderHook(() => useImportJob());

    await waitFor(() =>
      expect(result.current.error).toBe("import job not found"),
    );
    await act(() => result.current.scan(["codex"]));

    expect(result.current.job?.job_id).toBe("import-agent-a");
  });

  it("remains usable under Strict Mode", async () => {
    const { result } = renderHook(() => useImportJob(), {
      wrapper: ({ children }) => createElement(StrictMode, null, children),
    });

    await act(() => result.current.scan(["codex"]));

    expect(result.current.job?.job_id).toBe("import-agent-a");
  });

  it("ignores an older source detection response for the same agent", async () => {
    const oldDetection =
      deferred<Awaited<ReturnType<typeof portabilityImportApi.sources>>>();
    vi.mocked(portabilityImportApi.sources)
      .mockReturnValueOnce(oldDetection.promise)
      .mockResolvedValueOnce([
        { source: "qoder", name: "Qoder", detected: true },
      ]);
    const { result } = renderHook(() => useImportJob());

    let oldRequest!: ReturnType<typeof result.current.detect>;
    await act(async () => {
      oldRequest = result.current.detect();
      await result.current.detect();
    });
    expect(result.current.sources).toEqual([
      { source: "qoder", name: "Qoder", detected: true },
    ]);

    await act(async () => {
      oldDetection.resolve([
        { source: "codex", name: "Codex", detected: true },
      ]);
      await oldRequest;
    });
    expect(result.current.sources).toEqual([
      { source: "qoder", name: "Qoder", detected: true },
    ]);
  });

  it("ignores an older source detection rejection after recovery", async () => {
    const oldDetection =
      deferred<Awaited<ReturnType<typeof portabilityImportApi.sources>>>();
    vi.mocked(portabilityImportApi.sources)
      .mockReturnValueOnce(oldDetection.promise)
      .mockResolvedValueOnce([
        { source: "qoder", name: "Qoder", detected: true },
      ]);
    const { result } = renderHook(() => useImportJob());

    let oldRequest!: ReturnType<typeof result.current.detect>;
    await act(async () => {
      oldRequest = result.current.detect();
      await result.current.detect();
    });
    await act(async () => {
      oldDetection.reject(new Error("stale failure"));
      await oldRequest.catch(() => undefined);
    });

    expect(result.current.sources).toEqual([
      { source: "qoder", name: "Qoder", detected: true },
    ]);
    expect(result.current.error).toBe("");
    expect(result.current.loading).toBe(false);
  });

  it.each(["success", "failure"])(
    "keeps Agent B detection authoritative after late Agent A %s",
    async (lateOutcome) => {
      const agentA =
        deferred<Awaited<ReturnType<typeof portabilityImportApi.sources>>>();
      let agentBAttempts = 0;
      vi.mocked(portabilityImportApi.sources).mockImplementation((agentId) => {
        if (agentId === "agent-a") return agentA.promise;
        agentBAttempts += 1;
        return agentBAttempts === 1
          ? Promise.reject(new Error("Agent B unavailable"))
          : Promise.resolve([
              { source: "qoder", name: "Agent B Qoder", detected: true },
            ]);
      });
      const { result, rerender } = renderHook(() => useImportJob());

      let agentARequest!: ReturnType<typeof result.current.detect>;
      await act(async () => {
        agentARequest = result.current.detect();
        await Promise.resolve();
      });
      selectedAgent = "agent-b";
      rerender();

      expect(result.current.sources).toEqual([]);
      expect(result.current.loading).toBe(true);
      expect(result.current.error).toBe("");
      expect(result.current.detectError).toBe("");
      await act(async () => {
        await result.current.detect().catch(() => undefined);
      });
      expect(result.current.sources).toEqual([]);
      expect(result.current.detectError).toBe("Agent B unavailable");
      expect(result.current.loading).toBe(false);
      expect(portabilityImportApi.create).not.toHaveBeenCalled();

      await act(async () => {
        await result.current.detect();
      });
      expect(result.current.sources).toEqual([
        { source: "qoder", name: "Agent B Qoder", detected: true },
      ]);
      expect(result.current.detectError).toBe("");

      await act(async () => {
        if (lateOutcome === "success") {
          agentA.resolve([
            { source: "codex", name: "Late Agent A", detected: true },
          ]);
          await agentARequest;
        } else {
          agentA.reject(new Error("Late Agent A failure"));
          await agentARequest.catch(() => undefined);
        }
      });
      expect(result.current.sources).toEqual([
        { source: "qoder", name: "Agent B Qoder", detected: true },
      ]);
      expect(result.current.detectError).toBe("");
      expect(portabilityImportApi.create).not.toHaveBeenCalled();
    },
  );

  it("starts and retries only the currently selected agent's job", async () => {
    vi.mocked(portabilityImportApi.retry).mockImplementation(
      async (agentId) => ({
        ...job(agentId, `retry-${agentId}`),
        state: "running",
      }),
    );
    const { result } = renderHook(() => useImportJob());
    await act(() => result.current.scan(["codex"]));
    await act(() => result.current.start({ codex: { sessions: true } }));
    await act(() =>
      result.current.retry({ codex: { sessions: false, skills: ["skill-1"] } }),
    );

    expect(portabilityImportApi.start).toHaveBeenCalledWith(
      "agent-a",
      "import-agent-a",
      { codex: { sessions: true } },
      false,
    );
    expect(portabilityImportApi.retry).toHaveBeenCalledWith(
      "agent-a",
      "import-agent-a",
      { codex: { sessions: false, skills: ["skill-1"] } },
      false,
    );
    expect(result.current.job?.job_id).toBe("retry-agent-a");
  });

  it("cancels only the visible agent's job", async () => {
    const { result } = renderHook(() => useImportJob());
    await act(() => result.current.scan(["codex"]));
    await act(() => result.current.cancel());

    expect(portabilityImportApi.cancel).toHaveBeenCalledWith(
      "agent-a",
      "import-agent-a",
    );
    expect(result.current.job?.state).toBe("interrupted");
  });
});
