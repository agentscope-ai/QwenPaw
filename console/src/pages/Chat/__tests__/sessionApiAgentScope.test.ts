import { afterEach, describe, expect, it, vi } from "vitest";
import api, { type ChatSpec } from "../../../api";
import sessionApi from "../sessionApi";

function buildChat(id: string, sessionId = "console:default"): ChatSpec {
  return {
    id,
    session_id: sessionId,
    user_id: "default",
    channel: "console",
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T00:00:00Z",
    status: "running",
  };
}

describe("sessionApi agent scope", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionApi.setActiveAgent(`cleanup-${Date.now()}-${Math.random()}`);
  });

  it("clears chat aliases when the active agent changes", async () => {
    const listChats = vi
      .spyOn(api, "listChats")
      .mockResolvedValue([buildChat("agent-1-chat")]);

    sessionApi.setActiveAgent("agent-1");
    await sessionApi.getSessionList();
    expect(listChats).toHaveBeenCalledWith(
      { archived: false },
      { agentId: "agent-1" },
    );
    expect(sessionApi.getQueueSessionId("console:default")).toBe(
      "agent-1-chat",
    );

    sessionApi.setActiveAgent("agent-2");
    expect(sessionApi.isActiveAgent("agent-1")).toBe(false);
    expect(sessionApi.isActiveAgent("agent-2")).toBe(true);
    expect(sessionApi.getQueueSessionId("console:default")).toBe(
      "console:default",
    );
  });

  it("ignores a session-list response from the previously active agent", async () => {
    let resolveAgent1!: (chats: ChatSpec[]) => void;
    const agent1Response = new Promise<ChatSpec[]>((resolve) => {
      resolveAgent1 = resolve;
    });
    vi.spyOn(api, "listChats")
      .mockImplementationOnce(() => agent1Response)
      .mockResolvedValueOnce([buildChat("agent-2-chat")]);

    sessionApi.setActiveAgent("agent-1");
    const pendingAgent1List = sessionApi.getSessionList();

    sessionApi.setActiveAgent("agent-2");
    const agent2List = await sessionApi.getSessionList();
    resolveAgent1([buildChat("agent-1-chat")]);

    expect(await pendingAgent1List).toEqual([]);
    expect(agent2List.map((session) => session.id)).toEqual(["agent-2-chat"]);
    expect(sessionApi.getQueueSessionId("console:default")).toBe(
      "agent-2-chat",
    );
  });
});
