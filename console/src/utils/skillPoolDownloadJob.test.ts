import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  default: {
    startSkillPoolDownload: vi.fn(),
    getSkillPoolDownload: vi.fn(),
    cancelSkillPoolDownload: vi.fn(),
  },
}));

import api from "../api";
import { ApiError } from "../api/request";
import {
  POOL_DOWNLOAD_POLL_MS,
  startPoolDownloadJob,
} from "./skillPoolDownloadJob";

const payload = {
  skill_name: "demo",
  targets: [{ workspace_id: "ws-1" }],
};

const running = { job_id: "job-1", state: "running" as const };
const cancelling = { job_id: "job-1", state: "cancelling" as const };

const start = api.startSkillPoolDownload as unknown as ReturnType<typeof vi.fn>;
const poll = api.getSkillPoolDownload as unknown as ReturnType<typeof vi.fn>;
const cancel = api.cancelSkillPoolDownload as unknown as ReturnType<
  typeof vi.fn
>;

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  start.mockResolvedValue(running);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("startPoolDownloadJob cancellation", () => {
  it("shows cancelling before the request has been answered", async () => {
    let answer: (value: unknown) => void = () => {};
    cancel.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    poll.mockResolvedValue(running);
    const states: string[] = [];

    const handle = startPoolDownloadJob(payload, {
      onState: (state) => states.push(state),
    });
    const pending = handle.cancel();
    await Promise.resolve();
    await Promise.resolve();

    expect(states).toContain("cancelling");

    answer(cancelling);
    await pending;
  });

  it("ignores a running answer that arrives after cancellation started", async () => {
    cancel.mockResolvedValue(cancelling);
    poll.mockResolvedValue(running);
    const states: string[] = [];

    const handle = startPoolDownloadJob(payload, {
      onState: (state) => states.push(state),
    });
    await handle.cancel();

    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS * 2);

    expect(poll).toHaveBeenCalled();
    expect(states[states.length - 1]).toBe("cancelling");
  });

  it("does not revive a finished job when a late response arrives", async () => {
    let answer: (value: unknown) => void = () => {};
    cancel.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    poll.mockResolvedValue({ job_id: "job-1", state: "completed" });
    const states: string[] = [];

    const handle = startPoolDownloadJob(payload, {
      onState: (state) => states.push(state),
    });
    const pendingCancel = handle.cancel();
    await Promise.resolve();
    await Promise.resolve();

    expect(states).toContain("cancelling");

    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS);
    const job = await handle.done;
    expect(job.state).toBe("completed");

    // The DELETE answers after the job already finished: it must not move
    // the dialog back to "cancelling".
    answer(cancelling);
    await pendingCancel;

    expect(states[states.length - 1]).toBe("completed");
  });

  it("reports a failed cancel request and keeps tracking", async () => {
    cancel.mockRejectedValue(new Error("network down"));
    poll.mockResolvedValue(running);
    const states: string[] = [];

    const handle = startPoolDownloadJob(payload, {
      onState: (state) => states.push(state),
    });

    await expect(handle.cancel()).rejects.toThrow("network down");
    expect(states[states.length - 1]).toBe("running");
  });

  it("resolves the job from a terminal cancel response", async () => {
    cancel.mockResolvedValue({ job_id: "job-1", state: "cancelled" });
    poll.mockResolvedValue(running);

    const handle = startPoolDownloadJob(payload);
    await handle.cancel();

    await expect(handle.done).resolves.toMatchObject({
      state: "cancelled",
    });
    // Tracking ended on the DELETE answer; the next poll would only re-read
    // a state we already know.
    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS * 2);
    expect(poll).not.toHaveBeenCalled();
  });

  it("ignores a late cancel failure after a fatal status error", async () => {
    let rejectCancel: (error: unknown) => void = () => {};
    cancel.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectCancel = reject;
      }),
    );
    poll.mockRejectedValue(new ApiError(404, "Not Found"));
    const states: string[] = [];

    const handle = startPoolDownloadJob(payload, {
      onState: (state) => states.push(state),
    });
    const pendingCancel = handle.cancel().catch(() => {});
    const assertion = expect(handle.done).rejects.toThrow("Not Found");

    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS);
    await assertion;

    // The job is gone, so tracking already ended. The DELETE then fails
    // late; that must not restore a stale "running".
    rejectCancel(new Error("network down"));
    await pendingCancel;

    // The cancel was requested while the start request was still in flight,
    // so "running" is never shown. What matters is that the late DELETE
    // failure does not restore it after tracking already ended.
    expect(states.filter((state) => state === "running")).toHaveLength(0);
    expect(states[states.length - 1]).toBe("cancelling");
  });
});

describe("startPoolDownloadJob polling", () => {
  it("retries the status request after a connection failure", async () => {
    poll
      .mockRejectedValueOnce(new TypeError("Network Error"))
      .mockResolvedValueOnce({ job_id: "job-1", state: "completed" });

    const handle = startPoolDownloadJob(payload);
    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS);
    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS * 2);

    const job = await handle.done;
    expect(job.state).toBe("completed");
    expect(poll).toHaveBeenCalledTimes(2);
    expect(start).toHaveBeenCalledTimes(1);
    // The tracked request owns timeouts/network retries and can be aborted
    // when tracking ends; the loop owns HTTP status backoff.
    expect(poll.mock.calls[0][1]).toMatchObject({ retries: Infinity });
    expect(poll.mock.calls[0][1].signal).toBeDefined();
  });

  it("stops retrying when the job itself is gone", async () => {
    // `request()` throws ApiError, not an axios-shaped error.
    const gone = new ApiError(404, "Not Found");
    poll.mockRejectedValue(gone);

    const handle = startPoolDownloadJob(payload);
    const assertion = expect(handle.done).rejects.toThrow("Not Found");
    await vi.advanceTimersByTimeAsync(POOL_DOWNLOAD_POLL_MS);

    await assertion;
    expect(poll).toHaveBeenCalledTimes(1);
  });
});
