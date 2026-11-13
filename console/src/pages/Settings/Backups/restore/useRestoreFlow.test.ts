import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRestoreFlow } from "./useRestoreFlow";
import type { BackupMeta } from "@/api/types/backup";

function makeBackup(id: string): BackupMeta {
  return {
    id,
    name: id,
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

describe("useRestoreFlow", () => {
  it("handleRestore sets the pre-restore confirm target", () => {
    const { result } = renderHook(() => useRestoreFlow());
    const b = makeBackup("b1");

    act(() => {
      result.current.handleRestore(b);
    });

    expect(result.current.preRestoreConfirmTarget).toEqual(b);
    expect(result.current.restoreTarget).toBeNull();
    expect(result.current.preRestoreBackupTarget).toBeNull();
  });

  it("confirmRestoreWithoutBackup clears confirm target and sets restore target", () => {
    const { result } = renderHook(() => useRestoreFlow());
    const b = makeBackup("b1");

    act(() => {
      result.current.handleRestore(b);
    });
    act(() => {
      result.current.confirmRestoreWithoutBackup(b);
    });

    expect(result.current.preRestoreConfirmTarget).toBeNull();
    expect(result.current.restoreTarget).toEqual(b);
  });

  it("confirmRestoreWithBackup clears confirm target and sets backup target", () => {
    const { result } = renderHook(() => useRestoreFlow());
    const b = makeBackup("b1");

    act(() => {
      result.current.handleRestore(b);
    });
    act(() => {
      result.current.confirmRestoreWithBackup(b);
    });

    expect(result.current.preRestoreConfirmTarget).toBeNull();
    expect(result.current.preRestoreBackupTarget).toEqual(b);
    expect(result.current.restoreTarget).toBeNull();
  });

  it("cancelPreRestore clears confirm target", () => {
    const { result } = renderHook(() => useRestoreFlow());
    const b = makeBackup("b1");

    act(() => {
      result.current.handleRestore(b);
    });
    act(() => {
      result.current.cancelPreRestore();
    });

    expect(result.current.preRestoreConfirmTarget).toBeNull();
  });

  it("onPreRestoreBackupSuccess promotes backup target to restore target", () => {
    const { result } = renderHook(() => useRestoreFlow());
    const b = makeBackup("b1");

    act(() => {
      result.current.confirmRestoreWithBackup(b);
    });
    act(() => {
      result.current.onPreRestoreBackupSuccess();
    });

    expect(result.current.preRestoreBackupTarget).toBeNull();
    expect(result.current.restoreTarget).toEqual(b);
  });

  it("onPreRestoreBackupClose clears backup target without promoting", () => {
    const { result } = renderHook(() => useRestoreFlow());
    const b = makeBackup("b1");

    act(() => {
      result.current.confirmRestoreWithBackup(b);
    });
    act(() => {
      result.current.onPreRestoreBackupClose();
    });

    expect(result.current.preRestoreBackupTarget).toBeNull();
    expect(result.current.restoreTarget).toBeNull();
  });
});
