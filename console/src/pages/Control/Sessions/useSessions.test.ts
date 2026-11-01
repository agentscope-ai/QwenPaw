import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useSessions } from "./useSessions";

const mockMessage = { success: vi.fn(), error: vi.fn() };
const agentState = vi.hoisted(() => ({ selectedAgent: "agent-1" }));

vi.mock("../../../api", () => ({
  default: {
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    batchDeleteSessions: vi.fn(),
  },
}));
vi.mock("../../../api/modules/chat", () => ({
  chatApi: {
    listChats: vi.fn(),
    archiveChat: vi.fn(),
    unarchiveChat: vi.fn(),
    batchArchiveChats: vi.fn(),
    batchUnarchiveChats: vi.fn(),
  },
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({ selectedAgent: agentState.selectedAgent })),
}));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: vi.fn(() => ({ message: mockMessage })),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import api from "../../../api";
import { chatApi } from "../../../api/modules/chat";

type Session = { id: string; name: string; [key: string]: unknown };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("useSessions", () => {
  const mockSessions: Session[] = [
    { id: "s1", name: "Session 1" },
    { id: "s2", name: "Session 2" },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    agentState.selectedAgent = "agent-1";
    (chatApi.listChats as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockSessions,
    );
  });

  it("keeps imported archived chats out of the active tab", async () => {
    const active = { id: "import-active", name: "Active", archived: false };
    const archived = {
      id: "import-archived",
      name: "Archived",
      archived: true,
      archived_at: "2026-09-09T00:00:00Z",
    };
    (chatApi.listChats as ReturnType<typeof vi.fn>).mockResolvedValue([
      active,
      archived,
    ]);
    const { result } = renderHook(() => useSessions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.sessions).toEqual([active]);
    expect(result.current.activeCount).toBe(1);
    expect(result.current.archivedCount).toBe(1);
    act(() => result.current.setActiveTab("archived"));
    expect(result.current.sessions).toEqual([archived]);
  });

  // 1. 初始 loading=true，fetchSessions 成功后 loading=false
  it("初始 loading=true，fetchSessions 成功后 loading=false", async () => {
    const { result } = renderHook(() => useSessions());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
  });

  // 2. 初始挂载时调用 listSessions，sessions 被设置
  it("初始挂载时调用 listSessions，sessions 被设置", async () => {
    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(chatApi.listChats).toHaveBeenCalledWith({ agentId: "agent-1" });
    expect(result.current.sessions).toEqual(mockSessions);
  });

  it("keeps the newest agent result when the previous request resolves late", async () => {
    const agentA = deferred<Session[]>();
    const agentB = deferred<Session[]>();
    (chatApi.listChats as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(agentA.promise)
      .mockReturnValueOnce(agentB.promise);

    const { result, rerender } = renderHook(() => useSessions());
    const callbacks = {
      archiveSession: result.current.archiveSession,
      batchArchiveSessions: result.current.batchArchiveSessions,
      batchDeleteSessions: result.current.batchDeleteSessions,
      batchUnarchiveSessions: result.current.batchUnarchiveSessions,
      deleteSession: result.current.deleteSession,
      refreshSessions: result.current.refreshSessions,
      unarchiveSession: result.current.unarchiveSession,
      updateSession: result.current.updateSession,
    };
    agentState.selectedAgent = "agent-2";
    rerender();

    await act(async () => {
      agentB.resolve([{ id: "b", name: "Agent B" }]);
      await agentB.promise;
    });
    expect(result.current.sessions).toEqual([{ id: "b", name: "Agent B" }]);
    expect(result.current).toMatchObject(callbacks);

    await act(async () => {
      agentA.resolve([{ id: "a", name: "Agent A" }]);
      await agentA.promise;
    });
    expect(result.current.sessions).toEqual([{ id: "b", name: "Agent B" }]);
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("ignores a previous agent rejection after the new agent succeeds", async () => {
    const agentA = deferred<Session[]>();
    const agentB = deferred<Session[]>();
    (chatApi.listChats as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(agentA.promise)
      .mockReturnValueOnce(agentB.promise);

    const { result, rerender } = renderHook(() => useSessions());
    agentState.selectedAgent = "agent-2";
    rerender();

    await act(async () => {
      agentB.resolve([{ id: "b", name: "Agent B" }]);
      await agentB.promise;
    });
    await act(async () => {
      agentA.reject(new Error("late agent A failure"));
      await agentA.promise.catch(() => undefined);
    });

    expect(result.current.sessions).toEqual([{ id: "b", name: "Agent B" }]);
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("rejects stale row mutations without sending them as the new agent", async () => {
    const { result, rerender } = renderHook(() => useSessions());
    await waitFor(() => expect(result.current.sessions).toEqual(mockSessions));
    const staleOwner = result.current.agentId;
    const staleDelete = result.current.deleteSession;
    const staleUpdate = result.current.updateSession;
    const staleArchive = result.current.archiveSession;

    agentState.selectedAgent = "agent-2";
    rerender();
    let deleted: boolean | undefined;
    await act(async () => {
      deleted = await staleDelete("s1", staleOwner);
      await staleUpdate("s1", { name: "stale" }, staleOwner);
      await staleArchive("s1", staleOwner);
    });

    expect(deleted).toBe(false);
    expect(api.deleteSession).not.toHaveBeenCalled();
    expect(api.updateSession).not.toHaveBeenCalled();
    expect(chatApi.archiveChat).not.toHaveBeenCalled();
    expect(chatApi.listChats).toHaveBeenLastCalledWith({ agentId: "agent-2" });
  });

  it("exposes list errors and retries without resetting the active tab", async () => {
    const failure = new Error("list failed");
    const archived = {
      id: "archived-1",
      name: "Recovered session",
      archived: true,
    };
    (chatApi.listChats as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce([archived]);

    const { result } = renderHook(() => useSessions());
    const refreshSessions = result.current.refreshSessions;
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe(failure);
    expect(result.current.sessions).toEqual([]);
    act(() => result.current.setActiveTab("archived"));
    await act(async () => {
      await result.current.refreshSessions();
    });

    expect(result.current.refreshSessions).toBe(refreshSessions);
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.activeTab).toBe("archived");
    expect(result.current.sessions).toEqual([archived]);
    expect(chatApi.listChats).toHaveBeenCalledTimes(2);
  });

  it("keeps a successful empty list distinct from a request failure", async () => {
    (chatApi.listChats as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    const { result } = renderHook(() => useSessions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.sessions).toEqual([]);
  });

  // 3. updateSession 成功时更新 sessions 列表并调用 message.success
  it("updateSession 成功时更新 sessions 列表并调用 message.success", async () => {
    const updatedSession: Session = { id: "s1", name: "Updated Session 1" };
    (api.updateSession as ReturnType<typeof vi.fn>).mockResolvedValue(
      updatedSession,
    );

    const { result } = renderHook(() => useSessions());

    // 等待初始数据加载完成
    await waitFor(() => {
      expect(result.current.sessions).toEqual(mockSessions);
    });

    let returnValue: boolean | undefined;
    await act(async () => {
      returnValue = await result.current.updateSession("s1", {
        name: "Updated Session 1",
      });
    });

    expect(returnValue).toBe(true);
    expect(result.current.sessions[0]).toEqual(updatedSession);
    expect(result.current.sessions[1]).toEqual(mockSessions[1]);
    expect(mockMessage.success).toHaveBeenCalledWith("sessions.saveSuccess");
  });

  // 4. updateSession 失败时调用 message.error，返回 false
  it("updateSession 失败时调用 message.error，返回 false", async () => {
    (api.updateSession as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("update failed"),
    );

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let returnValue: boolean | undefined;
    await act(async () => {
      returnValue = await result.current.updateSession("s1", { name: "fail" });
    });

    expect(returnValue).toBe(false);
    expect(mockMessage.error).toHaveBeenCalledWith("sessions.saveFailed");
  });

  // 5. deleteSession 成功时从 sessions 移除并调用 message.success
  it("deleteSession 成功时从 sessions 移除并调用 message.success", async () => {
    (api.deleteSession as ReturnType<typeof vi.fn>).mockResolvedValue(
      undefined,
    );

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.sessions).toEqual(mockSessions);
    });

    let returnValue: boolean | undefined;
    await act(async () => {
      returnValue = await result.current.deleteSession("s1");
    });

    expect(returnValue).toBe(true);
    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.sessions[0].id).toBe("s2");
    expect(mockMessage.success).toHaveBeenCalledWith("sessions.deleteSuccess");
  });

  // 6. deleteSession 失败时调用 message.error，返回 false
  it("deleteSession 失败时调用 message.error，返回 false", async () => {
    (api.deleteSession as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("delete failed"),
    );

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let returnValue: boolean | undefined;
    await act(async () => {
      returnValue = await result.current.deleteSession("s1");
    });

    expect(returnValue).toBe(false);
    expect(mockMessage.error).toHaveBeenCalledWith("sessions.deleteFailed");
  });

  // 7. batchDeleteSessions 成功时批量移除并调用 message.success
  it("batchDeleteSessions 成功时批量移除并调用 message.success", async () => {
    (api.batchDeleteSessions as ReturnType<typeof vi.fn>).mockResolvedValue(
      undefined,
    );

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.sessions).toEqual(mockSessions);
    });

    let returnValue: boolean | undefined;
    await act(async () => {
      returnValue = await result.current.batchDeleteSessions(["s1"]);
    });

    expect(returnValue).toBe(true);
    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.sessions[0].id).toBe("s2");
    expect(mockMessage.success).toHaveBeenCalledWith(
      "sessions.batchDeleteSuccess",
    );
  });

  // 8. batchDeleteSessions 失败时调用 message.error，返回 false
  it("batchDeleteSessions 失败时调用 message.error，返回 false", async () => {
    (api.batchDeleteSessions as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("batch delete failed"),
    );

    const { result } = renderHook(() => useSessions());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let returnValue: boolean | undefined;
    await act(async () => {
      returnValue = await result.current.batchDeleteSessions(["s1", "s2"]);
    });

    expect(returnValue).toBe(false);
    expect(mockMessage.error).toHaveBeenCalledWith(
      "sessions.batchDeleteFailed",
    );
  });
});
