import { describe, it, expect, beforeEach, vi } from "vitest";
import { useSessionStore } from "./sessionStore";
import { DEFAULT_SESSION_NAME, SESSION_STATUS } from "../constants";
import type { ChatSession } from "../types";

// Mock chat API
vi.mock("../../../api/modules/chat", () => ({
  chatApi: {
    listChats: vi.fn().mockResolvedValue([]),
    createChat: vi.fn().mockResolvedValue({
      id: "mock-chat-id",
      session_id: "mock-session-id",
      user_id: "default",
      name: "New Chat",
    }),
    deleteChat: vi.fn().mockResolvedValue(undefined),
    batchDeleteChats: vi.fn().mockResolvedValue(undefined),
    updateChat: vi.fn().mockResolvedValue(undefined),
  },
}));

function makeSession(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    id: `s-${Date.now()}-${Math.random()}`,
    sessionId: "",
    userId: "",
    name: "Test Session",
    pinned: false,
    status: SESSION_STATUS.IDLE,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("sessionStore", () => {
  beforeEach(() => {
    useSessionStore.setState({
      sessions: [],
      loading: false,
      searchQuery: "",
    });
  });

  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  it("has empty initial state", () => {
    const state = useSessionStore.getState();
    expect(state.sessions).toEqual([]);
    expect(state.loading).toBe(false);
    expect(state.searchQuery).toBe("");
  });

  // -------------------------------------------------------------------------
  // createSession
  // -------------------------------------------------------------------------

  it("createSession adds a session to the beginning", async () => {
    const id = await useSessionStore.getState().createSession();
    const sessions = useSessionStore.getState().sessions;
    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe(id);
    expect(sessions[0].name).toBe(DEFAULT_SESSION_NAME);
  });

  // -------------------------------------------------------------------------
  // deleteSession
  // -------------------------------------------------------------------------

  it("deleteSession removes session by ID", async () => {
    useSessionStore.setState({
      sessions: [makeSession({ id: "s1" }), makeSession({ id: "s2" })],
    });
    await useSessionStore.getState().deleteSession("s1");
    const sessions = useSessionStore.getState().sessions;
    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe("s2");
  });

  // -------------------------------------------------------------------------
  // batchDeleteSessions
  // -------------------------------------------------------------------------

  it("batchDeleteSessions removes multiple sessions", async () => {
    useSessionStore.setState({
      sessions: [
        makeSession({ id: "s1" }),
        makeSession({ id: "s2" }),
        makeSession({ id: "s3" }),
      ],
    });
    await useSessionStore.getState().batchDeleteSessions(["s1", "s3"]);
    const sessions = useSessionStore.getState().sessions;
    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe("s2");
  });

  // -------------------------------------------------------------------------
  // renameSession
  // -------------------------------------------------------------------------

  it("renameSession updates session name", async () => {
    useSessionStore.setState({
      sessions: [makeSession({ id: "s1", name: "Old Name" })],
    });
    await useSessionStore.getState().renameSession("s1", "New Name");
    expect(useSessionStore.getState().sessions[0].name).toBe("New Name");
  });

  // -------------------------------------------------------------------------
  // pinSession
  // -------------------------------------------------------------------------

  it("pinSession toggles pinned state", async () => {
    useSessionStore.setState({
      sessions: [makeSession({ id: "s1", pinned: false })],
    });
    await useSessionStore.getState().pinSession("s1", true);
    expect(useSessionStore.getState().sessions[0].pinned).toBe(true);
  });

  // -------------------------------------------------------------------------
  // setSearchQuery
  // -------------------------------------------------------------------------

  it("setSearchQuery updates search query", () => {
    useSessionStore.getState().setSearchQuery("hello");
    expect(useSessionStore.getState().searchQuery).toBe("hello");
  });

  // -------------------------------------------------------------------------
  // filteredSessions
  // -------------------------------------------------------------------------

  it("filteredSessions returns all when query is empty", () => {
    useSessionStore.setState({
      sessions: [makeSession({ name: "Alpha" }), makeSession({ name: "Beta" })],
      searchQuery: "",
    });
    expect(useSessionStore.getState().filteredSessions()).toHaveLength(2);
  });

  it("filteredSessions filters by name", () => {
    useSessionStore.setState({
      sessions: [makeSession({ name: "Alpha" }), makeSession({ name: "Beta" })],
      searchQuery: "alp",
    });
    const result = useSessionStore.getState().filteredSessions();
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("Alpha");
  });

  it("filteredSessions filters by lastMessage", () => {
    useSessionStore.setState({
      sessions: [
        makeSession({ name: "X", lastMessage: "hello world" }),
        makeSession({ name: "Y", lastMessage: "foo bar" }),
      ],
      searchQuery: "hello",
    });
    const result = useSessionStore.getState().filteredSessions();
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("X");
  });

  // -------------------------------------------------------------------------
  // pinnedSessions
  // -------------------------------------------------------------------------

  it("pinnedSessions returns only pinned sessions", () => {
    useSessionStore.setState({
      sessions: [
        makeSession({ id: "s1", pinned: true }),
        makeSession({ id: "s2", pinned: false }),
        makeSession({ id: "s3", pinned: true }),
      ],
    });
    const pinned = useSessionStore.getState().pinnedSessions();
    expect(pinned).toHaveLength(2);
    expect(pinned.map((s) => s.id)).toEqual(["s1", "s3"]);
  });

  // -------------------------------------------------------------------------
  // updateSessionStatus
  // -------------------------------------------------------------------------

  it("updateSessionStatus changes session status", () => {
    useSessionStore.setState({
      sessions: [makeSession({ id: "s1", status: SESSION_STATUS.IDLE })],
    });
    useSessionStore.getState().updateSessionStatus("s1", "running");
    expect(useSessionStore.getState().sessions[0].status).toBe("running");
  });

  // -------------------------------------------------------------------------
  // updateSessionLastMessage
  // -------------------------------------------------------------------------

  it("updateSessionLastMessage updates lastMessage and updatedAt", () => {
    const oldDate = "2020-01-01T00:00:00.000Z";
    useSessionStore.setState({
      sessions: [makeSession({ id: "s1", updatedAt: oldDate })],
    });
    useSessionStore.getState().updateSessionLastMessage("s1", "new msg");
    const session = useSessionStore.getState().sessions[0];
    expect(session.lastMessage).toBe("new msg");
    expect(session.updatedAt).not.toBe(oldDate);
  });

  // -------------------------------------------------------------------------
  // groupedSessions
  // -------------------------------------------------------------------------

  it("groupedSessions puts pinned sessions first", () => {
    const now = new Date().toISOString();
    useSessionStore.setState({
      sessions: [
        makeSession({ id: "s1", pinned: true, updatedAt: now }),
        makeSession({ id: "s2", pinned: false, updatedAt: now }),
      ],
    });
    const groups = useSessionStore.getState().groupedSessions();
    expect(groups[0].label).toBe("Pinned");
    expect(groups[0].sessions[0].id).toBe("s1");
  });
});
