import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { ApiError } from "@/api/request";
import type {
  BackupJobSnapshot,
  CreateBackupRequest,
} from "@/api/types/backup";

const hoisted = vi.hoisted(() => ({
  apiMocks: {
    startBackupJob: vi.fn(),
    getActiveBackupJob: vi.fn(),
    getBackupJob: vi.fn(),
    cancelBackupJob: vi.fn(),
    streamBackupJob: vi.fn(),
  },
  messageMock: {
    success: vi.fn(),
    error: vi.fn(),
  },
  stableT: (k: string) => k,
}));

vi.mock("@/api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
}));

import { useBackupRunner } from "./useBackupRunner";

const { apiMocks, messageMock } = hoisted;

const data: CreateBackupRequest = {
  name: "n",
  scope: {
    include_agents: false,
    include_global_config: false,
    include_secrets: false,
    include_skill_pool: false,
  },
  agents: [],
};

const runningSnapshot: BackupJobSnapshot = {
  job_id: "job-1",
  backup_id: "backup-1",
  status: "running",
  phase: "preparing",
  percent: 0,
  current_agent: null,
  agent_index: 0,
  total_agents: 0,
  result: null,
  error: null,
};

const completedSnapshot: BackupJobSnapshot = {
  ...runningSnapshot,
  status: "completed",
  phase: "finalizing",
  percent: 100,
};

describe("useBackupRunner", () => {
  beforeEach(() => {
    apiMocks.startBackupJob.mockReset();
    apiMocks.getActiveBackupJob.mockReset();
    apiMocks.getBackupJob.mockReset();
    apiMocks.cancelBackupJob.mockReset();
    apiMocks.streamBackupJob.mockReset();
    apiMocks.getActiveBackupJob.mockResolvedValue(null);
    messageMock.success.mockReset();
    messageMock.error.mockReset();
  });

  it("start succeeds: loading toggles, message.success + onSuccess/onClose called", async () => {
    apiMocks.startBackupJob.mockResolvedValue(runningSnapshot);
    apiMocks.streamBackupJob.mockImplementation(
      async (
        _jobId: string,
        onSnapshot: (snapshot: BackupJobSnapshot) => void,
      ) => {
        onSnapshot(completedSnapshot);
      },
    );
    const onSuccess = vi.fn();
    const onClose = vi.fn();

    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess, onClose }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    expect(result.current.loading).toBe(false);
    expect(messageMock.success).toHaveBeenCalledWith("backup.createSuccess");
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("recovers from a lost event stream by polling job status", async () => {
    apiMocks.startBackupJob.mockResolvedValue(runningSnapshot);
    apiMocks.streamBackupJob.mockRejectedValue(new Error("stream lost"));
    apiMocks.getBackupJob.mockResolvedValue(completedSnapshot);
    const onSuccess = vi.fn();
    const onClose = vi.fn();

    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess, onClose }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    expect(apiMocks.getBackupJob).toHaveBeenCalledWith("job-1");
    expect(messageMock.success).toHaveBeenCalledWith("backup.createSuccess");
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
  });

  it("start with other error calls message.error('backup.createFailed')", async () => {
    apiMocks.startBackupJob.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess: vi.fn(), onClose: vi.fn() }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    expect(messageMock.error).toHaveBeenCalledWith("backup.createFailed");
    expect(result.current.loading).toBe(false);
  });

  it.each([false, true])(
    "observes an existing job after a start conflict only when enabled=%s",
    async (resumeActiveOnStartFailure) => {
      const otherJob = { ...runningSnapshot, job_id: "other-window-job" };
      apiMocks.startBackupJob.mockRejectedValue(
        new ApiError(409, "Another backup is running"),
      );
      apiMocks.getActiveBackupJob.mockResolvedValue(otherJob);
      apiMocks.streamBackupJob.mockImplementation(async (_id, onSnapshot) => {
        onSnapshot({ ...otherJob, status: "completed" });
      });
      const onSuccess = vi.fn();
      const onClose = vi.fn();
      const { result } = renderHook(() =>
        useBackupRunner({
          onSuccess,
          onClose,
          ...(resumeActiveOnStartFailure
            ? {}
            : { resumeActiveOnStartFailure: false }),
        }),
      );

      await act(async () => {
        await result.current.start(data);
      });

      expect(result.current.loading).toBe(false);
      expect(result.current.failed).toBe(!resumeActiveOnStartFailure);
      if (resumeActiveOnStartFailure) {
        expect(apiMocks.streamBackupJob).toHaveBeenCalledWith(
          otherJob.job_id,
          expect.any(Function),
          expect.any(AbortSignal),
        );
        expect(onSuccess).toHaveBeenCalledOnce();
      } else {
        expect(apiMocks.getActiveBackupJob).not.toHaveBeenCalled();
        expect(apiMocks.streamBackupJob).not.toHaveBeenCalled();
        expect(messageMock.error).toHaveBeenCalledWith("backup.createFailed");
        expect(onSuccess).not.toHaveBeenCalled();
        expect(onClose).not.toHaveBeenCalled();
      }
    },
  );

  it("reports a failed job and clears the failure on the next attempt", async () => {
    apiMocks.startBackupJob
      .mockResolvedValueOnce({ ...runningSnapshot, status: "failed" })
      .mockResolvedValueOnce(completedSnapshot);
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess, onClose }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    expect(result.current.failed).toBe(true);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.start(data);
    });

    expect(result.current.failed).toBe(false);
    expect(onSuccess).toHaveBeenCalledOnce();
  });

  it("waits for terminal cancellation, even after the request is accepted", async () => {
    apiMocks.startBackupJob.mockResolvedValue(runningSnapshot);
    apiMocks.cancelBackupJob.mockResolvedValue({
      ...runningSnapshot,
      status: "cancel_requested",
    });
    let emitTerminal: () => void;
    apiMocks.streamBackupJob.mockImplementation(
      (_jobId: string, onSnapshot: (snapshot: BackupJobSnapshot) => void) =>
        new Promise<void>((resolve) => {
          emitTerminal = () => {
            onSnapshot({ ...runningSnapshot, status: "cancelled" });
            resolve();
          };
        }),
    );
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess, onClose }),
    );

    void act(() => {
      result.current.start(data);
    });

    await waitFor(() => {
      expect(apiMocks.streamBackupJob).toHaveBeenCalled();
    });

    await act(async () => {
      await result.current.cancel();
      await result.current.cancel();
    });

    expect(apiMocks.cancelBackupJob).toHaveBeenCalledWith("job-1");
    expect(apiMocks.cancelBackupJob).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(true);
    expect(result.current.progressMsg).toBe("confirmation.cancellingBackup");

    await act(async () => emitTerminal());
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.failed).toBe(false);
    expect(result.current.progress).toBe(0);
    expect(result.current.progressMsg).toBe("");
  });

  it("reset clears progress state without calling onClose", async () => {
    apiMocks.startBackupJob.mockResolvedValue(runningSnapshot);
    apiMocks.streamBackupJob.mockImplementation(
      async (
        _jobId: string,
        onSnapshot: (snapshot: BackupJobSnapshot) => void,
      ) => {
        onSnapshot(completedSnapshot);
      },
    );
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess: vi.fn(), onClose }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.progress).toBe(0);
    expect(result.current.progressMsg).toBe("");
    // onClose was called once during start, but reset should not add another call
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
