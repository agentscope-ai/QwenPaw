import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

const mockListChats = vi.hoisted(() => vi.fn());

vi.mock("../../../api", () => ({
  default: {
    listChats: mockListChats,
    getChat: vi.fn(),
    deleteChat: vi.fn(),
  },
}));

describe("Chat sessionApi", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    mockListChats.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries local session id resolution until listChats contains the backend id", async () => {
    const { default: sessionApi } = await import("./index");
    const onSessionIdResolved = vi.fn();

    sessionApi.onSessionIdResolved = onSessionIdResolved;
    sessionApi.userInitiatedCreate = true;

    const createdSession: { id?: string; name: string } = { name: "New Chat" };
    await sessionApi.createSession(createdSession);

    const tempId = createdSession.id;
    expect(tempId).toBeTruthy();

    mockListChats.mockResolvedValueOnce([]).mockResolvedValueOnce([
      {
        id: "backend-session-id",
        name: "New Chat",
        session_id: tempId,
        user_id: "default",
        channel: "console",
        status: "idle",
        meta: {},
      },
    ]);

    sessionApi.triggerResolve(tempId!);
    await vi.waitFor(() => expect(mockListChats).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(500);

    await vi.waitFor(() =>
      expect(onSessionIdResolved).toHaveBeenCalledWith(
        tempId,
        "backend-session-id",
      ),
    );
  });

  it("maps a resolved backend chat id back to the SDK session id and backend session id", async () => {
    const { default: sessionApi } = await import("./index");

    sessionApi.userInitiatedCreate = true;
    const createdSession: { id?: string; name: string } = { name: "New Chat" };
    await sessionApi.createSession(createdSession);

    const tempId = createdSession.id;
    expect(tempId).toBeTruthy();

    mockListChats.mockResolvedValueOnce([
      {
        id: "backend-chat-id",
        name: "New Chat",
        session_id: tempId,
        user_id: "default",
        channel: "console",
        status: "idle",
        meta: {},
      },
    ]);

    sessionApi.triggerResolve(tempId!);

    await vi.waitFor(() =>
      expect(sessionApi.getLibrarySessionId("backend-chat-id")).toBe(tempId),
    );
    expect(sessionApi.getBackendSessionId("backend-chat-id")).toBe(tempId);
  });
});
