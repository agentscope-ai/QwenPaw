import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

vi.mock("../../utils/downloadFileFromUrl", () => ({
  downloadFileFromUrl: vi.fn(),
}));

import { agentsApi } from "./agents";
import { request } from "../request";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";

describe("agentsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("listAgents calls GET /agents", async () => {
    const data = { agents: [] };
    vi.mocked(request).mockResolvedValue(data);
    const result = await agentsApi.listAgents();
    expect(request).toHaveBeenCalledWith("/agents");
    expect(result).toEqual(data);
  });

  it("getAgent calls GET /agents/${id}", async () => {
    const data = { name: "a1" } as any;
    vi.mocked(request).mockResolvedValue(data);
    const result = await agentsApi.getAgent("a1");
    expect(request).toHaveBeenCalledWith("/agents/a1");
    expect(result).toEqual(data);
  });

  it("createAgent sends POST /agents with JSON body", async () => {
    const agent = { name: "new" } as any;
    const ref = { agent_id: "x" } as any;
    vi.mocked(request).mockResolvedValue(ref);
    const result = await agentsApi.createAgent(agent);
    expect(request).toHaveBeenCalledWith("/agents", {
      method: "POST",
      body: JSON.stringify(agent),
    });
    expect(result).toEqual(ref);
  });

  it("updateAgent sends PUT /agents/${id} with JSON body", async () => {
    const agent = { name: "updated" } as any;
    vi.mocked(request).mockResolvedValue(agent);
    const result = await agentsApi.updateAgent("a1", agent);
    expect(request).toHaveBeenCalledWith("/agents/a1", {
      method: "PUT",
      body: JSON.stringify(agent),
    });
    expect(result).toEqual(agent);
  });

  it("exports an owner Agent through the authenticated download helper", async () => {
    await agentsApi.exportPortableAgent("agent / 1", "Portable Agent");

    expect(downloadFileFromUrl).toHaveBeenCalledWith(
      "/api/agents/agent%20%2F%201/portable-package",
      "Portable Agent.qwenpaw-agent.zip",
      expect.objectContaining({ preferResponseFilename: true }),
    );
  });

  it("imports an Agent package as multipart form data", async () => {
    const file = new File(["zip"], "agent.zip", { type: "application/zip" });
    const response = {
      agent_id: "imported",
      name: "Imported",
      status: "draft",
      requires_reauthorization: true,
      dependencies: {},
    } as const;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify(response), { status: 201 }),
      );

    await expect(agentsApi.importPortableAgent(file)).resolves.toEqual(
      response,
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/agents/portable-package/import",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
  });

  it("updates third-party model settings from Chat", async () => {
    await agentsApi.updateBackendSettings("a1", {
      model: "gpt-test-codex",
      reasoning_effort: "high",
    });
    expect(request).toHaveBeenCalledWith("/agents/a1/backend-settings", {
      method: "PATCH",
      body: JSON.stringify({
        model: "gpt-test-codex",
        reasoning_effort: "high",
      }),
    });
  });

  it("rebuildMemoryIndex sends POST with an extended timeout", async () => {
    const resp = { status: "completed" } as const;
    vi.mocked(request).mockResolvedValue(resp);
    const result = await agentsApi.rebuildMemoryIndex("a1");
    expect(request).toHaveBeenCalledWith("/agents/a1/memory/reindex", {
      method: "POST",
      timeout: 10 * 60 * 1000,
    });
    expect(result).toEqual(resp);
  });

  it("getMemoryStatus fetches structured ReMe status", async () => {
    const status = {
      components: {},
      components_total: "0 B",
      process_rss: "1.00 KiB",
    };
    vi.mocked(request).mockResolvedValue(status);

    const result = await agentsApi.getMemoryStatus("a1");

    expect(request).toHaveBeenCalledWith("/agents/a1/memory/status");
    expect(result).toEqual(status);
  });

  it("getMemoryStatus forwards a cancellation signal", async () => {
    const controller = new AbortController();

    await agentsApi.getMemoryStatus("a1", controller.signal);

    expect(request).toHaveBeenCalledWith("/agents/a1/memory/status", {
      signal: controller.signal,
    });
  });

  it("getMemoryGraph loads the indexed wikilink graph", async () => {
    const graph = { version: 1, nodes: [], edges: [] } as const;
    vi.mocked(request).mockResolvedValue(graph);
    const result = await agentsApi.getMemoryGraph("a1");
    expect(request).toHaveBeenCalledWith("/agents/a1/memory/graph");
    expect(result).toEqual(graph);
  });

  it("deleteAgent sends DELETE /agents/${id}", async () => {
    const resp = { success: true, agent_id: "a1" };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await agentsApi.deleteAgent("a1");
    expect(request).toHaveBeenCalledWith("/agents/a1", {
      method: "DELETE",
    });
    expect(result).toEqual(resp);
  });

  it("reorderAgents sends PUT /agents/order with agent_ids", async () => {
    const resp = { success: true, agent_ids: ["a", "b"] } as any;
    vi.mocked(request).mockResolvedValue(resp);
    const result = await agentsApi.reorderAgents(["a", "b"]);
    expect(request).toHaveBeenCalledWith("/agents/order", {
      method: "PUT",
      body: JSON.stringify({ agent_ids: ["a", "b"] }),
    });
    expect(result).toEqual(resp);
  });

  it("toggleAgentEnabled sends PATCH with enabled flag", async () => {
    const resp = { success: true, agent_id: "a1", enabled: true };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await agentsApi.toggleAgentEnabled("a1", true);
    expect(request).toHaveBeenCalledWith("/agents/a1/toggle", {
      method: "PATCH",
      body: JSON.stringify({ enabled: true }),
    });
    expect(result).toEqual(resp);
  });

  it("setAgentPinned sends PATCH with pinned flag", async () => {
    const resp = { success: true, agent_id: "a1", pinned: true };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await agentsApi.setAgentPinned("a1", true);
    expect(request).toHaveBeenCalledWith("/agents/a1/pin", {
      method: "PATCH",
      body: JSON.stringify({ pinned: true }),
    });
    expect(result).toEqual(resp);
  });

  it("memory maintenance carries the explicit governance target", async () => {
    const context = {
      agentId: "governed-agent",
      governance: true,
    } as const;

    await agentsApi.rebuildMemoryIndex("governed-agent", context);
    await agentsApi.getMemoryRuntimeStatus(
      "governed-agent",
      undefined,
      context,
    );

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/agents/governed-agent/memory/reindex",
      {
        method: "POST",
        timeout: 10 * 60 * 1000,
        headers: {
          "X-Agent-Id": "governed-agent",
          "X-Agent-Governance": "runtime-config",
        },
      },
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/agents/governed-agent/memory/runtime-status",
      {
        headers: {
          "X-Agent-Id": "governed-agent",
          "X-Agent-Governance": "runtime-config",
        },
      },
    );
  });

  it("manages Agent members through owner-scoped endpoints", async () => {
    await agentsApi.listMembers("a1");
    expect(request).toHaveBeenLastCalledWith("/agents/a1/members");

    await agentsApi.grantMember("a1", "user-1", "collaborator");
    expect(request).toHaveBeenLastCalledWith("/agents/a1/members/user-1", {
      method: "PUT",
      body: JSON.stringify({ role: "collaborator" }),
    });

    await agentsApi.revokeMember("a1", "user-1");
    expect(request).toHaveBeenLastCalledWith("/agents/a1/members/user-1", {
      method: "DELETE",
    });
  });

  it("uses explicit admin governance endpoints for public and config", async () => {
    await agentsApi.listAdminAgents();
    expect(request).toHaveBeenLastCalledWith("/admin/agents");

    await agentsApi.setPublication("a1", true);
    expect(request).toHaveBeenLastCalledWith("/admin/agents/a1/publication", {
      method: "PATCH",
      body: JSON.stringify({ published: true }),
    });

    const config = { id: "a1", name: "Updated" } as any;
    await agentsApi.updateAdminAgent("a1", config);
    expect(request).toHaveBeenLastCalledWith("/admin/agents/a1/config", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  });
});
