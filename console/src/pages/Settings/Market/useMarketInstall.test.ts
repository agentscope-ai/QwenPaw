/**
 * Market skill install queue — enqueue/cancel/retry lifecycle for pool and
 * workspace targets, including poll-driven workspace installs, timeout
 * aborts and cache invalidation on success.
 * Regression family: settings round-trip (installed skill must show up
 * immediately) and install-status UI consistency.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  startHubSkillInstall: vi.fn(),
  getHubSkillInstallStatus: vi.fn(),
  cancelHubSkillInstall: vi.fn(),
  importPoolSkillFromHub: vi.fn(),
  invalidateSkillCache: vi.fn(),
  notifySkillChange: vi.fn(),
}));

vi.mock("../../../api", () => ({
  default: {
    startHubSkillInstall: (...a: unknown[]) => mocks.startHubSkillInstall(...a),
    getHubSkillInstallStatus: (...a: unknown[]) =>
      mocks.getHubSkillInstallStatus(...a),
    cancelHubSkillInstall: (...a: unknown[]) =>
      mocks.cancelHubSkillInstall(...a),
    importPoolSkillFromHub: (...a: unknown[]) =>
      mocks.importPoolSkillFromHub(...a),
  },
}));

vi.mock("../../../api/modules/skill", () => ({
  invalidateSkillCache: (...a: unknown[]) => mocks.invalidateSkillCache(...a),
}));

vi.mock("../../../utils/skillChangeEvents", () => ({
  notifySkillChange: (...a: unknown[]) => mocks.notifySkillChange(...a),
}));

import { useMarketInstall } from "./useMarketInstall";

const skillResult = {
  source: "github",
  slug: "cool-skill",
  source_url: "https://example.com/cool-skill.zip",
  version: "1.2.0",
  name: "Cool Skill",
  description: null,
  author: null,
  icon_url: null,
  stats: null,
};

async function flush() {
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await flush();
}

function mount(hooks?: {
  onSuccess?: (item: unknown) => void;
  onError?: (item: unknown) => void;
}) {
  return renderHook(() =>
    useMarketInstall({
      selectedAgent: "agent-1",
      onSuccess: hooks?.onSuccess,
      onError: hooks?.onError,
    } as never),
  );
}

describe("useMarketInstall — pool installs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("completes a pool install and fires onSuccess", async () => {
    const onSuccess = vi.fn();
    mocks.importPoolSkillFromHub.mockResolvedValue({ name: "cool-skill" });
    const { result } = mount({ onSuccess });

    act(() => {
      result.current.enqueue([skillResult], "pool");
    });
    await flush();

    expect(result.current.queue).toHaveLength(1);
    expect(result.current.queue[0].status).toBe("completed");
    expect(result.current.queue[0].installedName).toBe("cool-skill");
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(mocks.invalidateSkillCache).toHaveBeenCalledWith({ pool: true });
  });

  it("marks a failed pool install with the server message", async () => {
    const onError = vi.fn();
    mocks.importPoolSkillFromHub.mockRejectedValue(new Error("scan blocked"));
    const { result } = mount({ onError });

    act(() => {
      result.current.enqueue([skillResult], "pool");
    });
    await flush();

    expect(result.current.queue[0].status).toBe("failed");
    expect(result.current.queue[0].message).toBe("scan blocked");
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("cancels an in-flight pool install after import resolves", async () => {
    let resolveImport!: (v: unknown) => void;
    mocks.importPoolSkillFromHub.mockReturnValue(
      new Promise((res) => {
        resolveImport = res;
      }),
    );
    const { result } = mount();

    let itemId = "";
    act(() => {
      const items = result.current.enqueue([skillResult], "pool");
      itemId = items[0].id;
    });
    await flush();
    expect(result.current.queue[0].status).toBe("installing");

    act(() => {
      result.current.cancel(itemId);
    });
    await act(async () => {
      resolveImport({ name: "cool-skill" });
    });
    await flush();

    expect(result.current.queue[0].status).toBe("cancelled");
    expect(mocks.invalidateSkillCache).not.toHaveBeenCalled();
  });

  it("cancels a queued (not yet started) item immediately", async () => {
    let resolveFirst!: (v: unknown) => void;
    mocks.importPoolSkillFromHub.mockImplementation(() => {
      if (mocks.importPoolSkillFromHub.mock.calls.length === 1) {
        return new Promise((res) => {
          resolveFirst = res;
        });
      }
      return Promise.resolve({ name: "second" });
    });
    const { result } = mount();

    let secondId = "";
    act(() => {
      const items = result.current.enqueue(
        [
          { ...skillResult, slug: "one" },
          { ...skillResult, slug: "two" },
        ],
        "pool",
      );
      secondId = items[1].id;
    });
    await flush();

    act(() => {
      result.current.cancel(secondId);
    });
    await flush();
    expect(result.current.queue.find((it) => it.id === secondId)?.status).toBe(
      "cancelled",
    );

    await act(async () => {
      resolveFirst({ name: "first" });
    });
    await flush();
    // The cancelled item never runs; queue drains.
    expect(result.current.queue[0].status).toBe("completed");
    expect(mocks.importPoolSkillFromHub).toHaveBeenCalledTimes(1);
  });

  it("installs queued items sequentially", async () => {
    mocks.importPoolSkillFromHub
      .mockResolvedValueOnce({ name: "first" })
      .mockResolvedValueOnce({ name: "second" });
    const { result } = mount();

    act(() => {
      result.current.enqueue(
        [
          { ...skillResult, slug: "one" },
          { ...skillResult, slug: "two" },
        ],
        "pool",
      );
    });
    await flush();

    expect(mocks.importPoolSkillFromHub).toHaveBeenCalledTimes(2);
    expect(result.current.queue.map((it) => it.status)).toEqual([
      "completed",
      "completed",
    ]);
  });

  it("retry re-queues a failed item and reruns it", async () => {
    const onSuccess = vi.fn();
    mocks.importPoolSkillFromHub
      .mockRejectedValueOnce(new Error("transient"))
      .mockResolvedValueOnce({ name: "cool-skill" });
    const { result } = mount({ onSuccess });

    let itemId = "";
    act(() => {
      const items = result.current.enqueue([skillResult], "pool");
      itemId = items[0].id;
    });
    await flush();
    expect(result.current.queue[0].status).toBe("failed");

    act(() => {
      result.current.retry(itemId);
    });
    await flush();

    expect(result.current.queue[0].status).toBe("completed");
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("retry is a no-op for unknown ids", async () => {
    mocks.importPoolSkillFromHub.mockResolvedValue({ name: "x" });
    const { result } = mount();
    act(() => {
      result.current.enqueue([skillResult], "pool");
    });
    await flush();
    const before = result.current.queue;
    act(() => {
      result.current.retry("nope");
    });
    await flush();
    expect(result.current.queue).toEqual(before);
  });

  it("clearFinished keeps queued and installing items only", async () => {
    let hangResolve!: (v: unknown) => void;
    mocks.importPoolSkillFromHub.mockImplementation(() => {
      if (mocks.importPoolSkillFromHub.mock.calls.length === 1) {
        return new Promise((res) => {
          hangResolve = res;
        });
      }
      return Promise.resolve({ name: "later" });
    });
    const { result } = mount();

    act(() => {
      result.current.enqueue(
        [
          { ...skillResult, slug: "hang" },
          { ...skillResult, slug: "done" },
        ],
        "pool",
      );
    });
    await flush();
    // First item is installing (hung), second is queued behind it.
    expect(result.current.queue.map((it) => it.status)).toEqual([
      "installing",
      "queued",
    ]);

    act(() => {
      result.current.clearFinished();
    });
    expect(result.current.queue.map((it) => it.status)).toEqual([
      "installing",
      "queued",
    ]);

    await act(async () => {
      hangResolve({ name: "done-hang" });
    });
    await flush();

    act(() => {
      result.current.clearFinished();
    });
    expect(result.current.queue).toHaveLength(0);
  });
});

describe("useMarketInstall — workspace installs (polling)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls until completion, notifies skill change", async () => {
    mocks.startHubSkillInstall.mockResolvedValue({ task_id: "t1" });
    mocks.getHubSkillInstallStatus
      .mockResolvedValueOnce({ status: "installing" })
      .mockResolvedValueOnce({
        status: "completed",
        result: { installed: true, name: "cool-skill" },
      });
    const onSuccess = vi.fn();
    const { result } = mount({ onSuccess });

    act(() => {
      result.current.enqueue([skillResult], "workspace");
    });
    await flush();
    expect(result.current.queue[0].status).toBe("installing");

    await advance(1000);
    await advance(1000);

    expect(result.current.queue[0].status).toBe("completed");
    expect(result.current.queue[0].installedName).toBe("cool-skill");
    expect(mocks.notifySkillChange).toHaveBeenCalledWith("agent-1");
    expect(mocks.invalidateSkillCache).toHaveBeenCalledWith({
      agentId: "agent-1",
      workspaces: true,
    });
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("surfaces the server error on a failed poll", async () => {
    mocks.startHubSkillInstall.mockResolvedValue({ task_id: "t1" });
    mocks.getHubSkillInstallStatus.mockResolvedValue({
      status: "failed",
      error: "dependency missing",
    });
    const onError = vi.fn();
    const { result } = mount({ onError });

    act(() => {
      result.current.enqueue([skillResult], "workspace");
    });
    await flush();
    await advance(1000);

    expect(result.current.queue[0].status).toBe("failed");
    expect(result.current.queue[0].message).toBe("dependency missing");
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("treats a server-side cancel as cancelled", async () => {
    mocks.startHubSkillInstall.mockResolvedValue({ task_id: "t1" });
    mocks.getHubSkillInstallStatus.mockResolvedValue({ status: "cancelled" });
    const { result } = mount();

    act(() => {
      result.current.enqueue([skillResult], "workspace");
    });
    await flush();
    await advance(1000);

    expect(result.current.queue[0].status).toBe("cancelled");
  });

  it("cancels the running task when the user cancels mid-poll", async () => {
    mocks.startHubSkillInstall.mockResolvedValue({ task_id: "t1" });
    mocks.getHubSkillInstallStatus.mockResolvedValue({ status: "installing" });
    const { result } = mount();

    let itemId = "";
    act(() => {
      const items = result.current.enqueue([skillResult], "workspace");
      itemId = items[0].id;
    });
    await flush();
    expect(result.current.queue[0].status).toBe("installing");

    act(() => {
      result.current.cancel(itemId);
    });
    await advance(1000);

    expect(mocks.cancelHubSkillInstall).toHaveBeenCalledWith("t1", "agent-1");
    expect(result.current.queue[0].status).toBe("cancelled");
  });

  it("times out after 90s and aborts the task", async () => {
    mocks.startHubSkillInstall.mockResolvedValue({ task_id: "t1" });
    mocks.getHubSkillInstallStatus.mockResolvedValue({ status: "installing" });
    const { result } = mount();

    act(() => {
      result.current.enqueue([skillResult], "workspace");
    });
    await flush();

    // Drive past the 90s timeout in 15s steps.
    for (let i = 0; i < 7; i++) await advance(15_000);

    expect(mocks.cancelHubSkillInstall).toHaveBeenCalledWith("t1", "agent-1");
    expect(result.current.queue[0].status).toBe("failed");
    expect(result.current.queue[0].message).toBe("__TIMED_OUT__");
  });

  it("passes override name and version to the installer", async () => {
    mocks.startHubSkillInstall.mockResolvedValue({ task_id: "t1" });
    mocks.getHubSkillInstallStatus.mockResolvedValue({
      status: "completed",
      result: { installed: true, name: "renamed" },
    });
    const { result } = mount();

    act(() => {
      result.current.enqueue([{ ...skillResult, version: "" }], "workspace");
    });
    await flush();
    await advance(1000);

    expect(mocks.startHubSkillInstall).toHaveBeenCalledWith(
      expect.objectContaining({
        bundle_url: skillResult.source_url,
        enable: true,
      }),
      "agent-1",
    );
    // Empty version normalizes to undefined
    const args = mocks.startHubSkillInstall.mock.calls[0][0];
    expect(args.version).toBeUndefined();
  });
});
