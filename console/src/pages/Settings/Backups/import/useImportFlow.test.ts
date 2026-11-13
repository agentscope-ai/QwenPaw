import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useImportFlow } from "./useImportFlow";
import type { BackupMeta } from "@/api/types/backup";

const hoisted = vi.hoisted(() => ({
  apiMocks: {
    importBackup: vi.fn(),
    resolveImportConflict: vi.fn(),
  },
  messageMock: {
    success: vi.fn(),
    error: vi.fn(),
  },
  stableT: (k: string) => k,
  trustModeFromErrorMock: vi.fn(),
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

vi.mock("../trust/trustErrors", () => ({
  trustModeFromError: hoisted.trustModeFromErrorMock,
}));

const { apiMocks, messageMock, trustModeFromErrorMock } = hoisted;

function makeExisting(): BackupMeta {
  return {
    id: "old",
    name: "old backup",
    description: "",
    created_at: "",
    scope: {
      include_agents: false,
      include_global_config: false,
      include_secrets: false,
      include_skill_pool: false,
    },
    agent_count: 0,
  };
}

describe("useImportFlow", () => {
  beforeEach(() => {
    apiMocks.importBackup.mockReset();
    apiMocks.resolveImportConflict.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    trustModeFromErrorMock.mockReset();
    trustModeFromErrorMock.mockReturnValue(null);
  });

  it("handleImport success calls message.success and onSuccess", async () => {
    apiMocks.importBackup.mockResolvedValue(undefined);
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useImportFlow({ onSuccess }));

    await act(async () => {
      await result.current.handleImport(new File([], "x.zip"));
    });

    expect(messageMock.success).toHaveBeenCalledWith("backup.importSuccess");
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("handleImport 409 backup_conflict stores conflict meta", async () => {
    const existing = makeExisting();
    apiMocks.importBackup.mockRejectedValue({
      conflict: {
        detail: "backup_conflict",
        existing,
        pending_token: "tok-1",
      },
    });

    const { result } = renderHook(() => useImportFlow({ onSuccess: vi.fn() }));

    await act(async () => {
      await result.current.handleImport(new File([], "x.zip"));
    });

    expect(result.current.conflictMeta).toEqual(existing);
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("handleImport trust error sets trustPrompt", async () => {
    trustModeFromErrorMock.mockReturnValue("legacy");
    apiMocks.importBackup.mockRejectedValue(new Error("trust needed"));

    const { result } = renderHook(() => useImportFlow({ onSuccess: vi.fn() }));
    const file = new File([], "legacy.zip");

    await act(async () => {
      await result.current.handleImport(file);
    });

    expect(result.current.trustFileName).toBe("legacy.zip");
    expect(result.current.trustMode).toBe("legacy");
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("handleImport ordinary error calls message.error", async () => {
    apiMocks.importBackup.mockRejectedValue(new Error("bad zip"));

    const { result } = renderHook(() => useImportFlow({ onSuccess: vi.fn() }));

    await act(async () => {
      await result.current.handleImport(new File([], "x.zip"));
    });

    expect(messageMock.error).toHaveBeenCalledWith("backup.importFailed");
    expect(result.current.conflictMeta).toBeNull();
    expect(result.current.trustFileName).toBeNull();
  });

  it("handleConflictChoice success resolves conflict and calls onSuccess", async () => {
    apiMocks.resolveImportConflict.mockResolvedValue(undefined);
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useImportFlow({ onSuccess }));

    // seed a conflict token via handleImport
    apiMocks.importBackup.mockRejectedValueOnce({
      conflict: {
        detail: "backup_conflict",
        existing: makeExisting(),
        pending_token: "tok-2",
      },
    });
    await act(async () => {
      await result.current.handleImport(new File([], "x.zip"));
    });

    await act(async () => {
      await result.current.handleConflictChoice();
    });

    expect(apiMocks.resolveImportConflict).toHaveBeenCalledWith("tok-2");
    expect(messageMock.success).toHaveBeenCalledWith("backup.importSuccess");
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("clearConflict clears conflict meta", async () => {
    apiMocks.importBackup.mockRejectedValue({
      conflict: {
        detail: "backup_conflict",
        existing: makeExisting(),
        pending_token: "tok-3",
      },
    });
    const { result } = renderHook(() => useImportFlow({ onSuccess: vi.fn() }));

    await act(async () => {
      await result.current.handleImport(new File([], "x.zip"));
    });
    expect(result.current.conflictMeta).not.toBeNull();

    act(() => {
      result.current.clearConflict();
    });

    expect(result.current.conflictMeta).toBeNull();
  });
});
