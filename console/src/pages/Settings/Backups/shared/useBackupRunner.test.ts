import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { CreateBackupRequest } from "@/api/types/backup";

const hoisted = vi.hoisted(() => ({
  apiMocks: {
    createBackupStream: vi.fn(),
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

describe("useBackupRunner", () => {
  beforeEach(() => {
    apiMocks.createBackupStream.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
  });

  it("start succeeds: loading toggles, message.success + onSuccess/onClose called", async () => {
    apiMocks.createBackupStream.mockImplementation(
      async (_data: unknown, onEvent: (e: { type: string }) => void) => {
        onEvent({ type: "done" });
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

  it("start with AbortError stays silent (no message.error)", async () => {
    const abortErr = new Error("aborted");
    abortErr.name = "AbortError";
    apiMocks.createBackupStream.mockRejectedValue(abortErr);

    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess: vi.fn(), onClose: vi.fn() }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    expect(messageMock.error).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
  });

  it("start with other error calls message.error('backup.createFailed')", async () => {
    apiMocks.createBackupStream.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess: vi.fn(), onClose: vi.fn() }),
    );

    await act(async () => {
      await result.current.start(data);
    });

    expect(messageMock.error).toHaveBeenCalledWith("backup.createFailed");
    expect(result.current.loading).toBe(false);
  });

  it("cancel calls onClose and resets state", async () => {
    apiMocks.createBackupStream.mockImplementation(
      async () => new Promise(() => {}),
    );
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useBackupRunner({ onSuccess: vi.fn(), onClose }),
    );

    act(() => {
      result.current.start(data);
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(true);
    });

    act(() => {
      result.current.cancel();
    });

    expect(onClose).toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.progress).toBe(0);
    expect(result.current.progressMsg).toBe("");
  });

  it("reset clears progress state without calling onClose", async () => {
    apiMocks.createBackupStream.mockImplementation(
      async (_d: unknown, onEvent: (e: { type: string }) => void) => {
        onEvent({ type: "done" });
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
