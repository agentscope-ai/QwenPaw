import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/modules/agents", () => ({
  agentsApi: { listAgents: vi.fn() },
}));

vi.mock("../plugins/registry/store", () => ({
  menuRegistry: { refresh: vi.fn() },
}));

const STORAGE_KEY = "qwenpaw-agent-storage";

async function loadFreshStore() {
  vi.resetModules();
  return import("./agentStore");
}

describe("agentStore URL initialization", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  it("persists a URL agent on a cold load before the first request", async () => {
    window.history.replaceState({}, "", "/chat/sales/session-1");

    const { useAgentStore } = await loadFreshStore();
    const { buildAuthHeaders } = await import("../api/authHeaders");

    expect(useAgentStore.getState().selectedAgent).toBe("sales");
    expect(buildAuthHeaders()["X-Agent-Id"]).toBe("sales");
    expect(
      JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "null")?.state
        ?.selectedAgent,
    ).toBe("sales");
  });

  it("reads the URL agent under the /console router basename", async () => {
    const persisted = JSON.stringify({
      state: { selectedAgent: "default", lastChatIdByAgent: {} },
      version: 0,
    });
    sessionStorage.setItem(STORAGE_KEY, persisted);
    localStorage.setItem(STORAGE_KEY, persisted);
    window.history.replaceState({}, "", "/console/chat/sales/session-1");

    const { useAgentStore } = await loadFreshStore();
    const { buildAuthHeaders } = await import("../api/authHeaders");

    expect(useAgentStore.getState().selectedAgent).toBe("sales");
    expect(buildAuthHeaders()["X-Agent-Id"]).toBe("sales");
  });
});
