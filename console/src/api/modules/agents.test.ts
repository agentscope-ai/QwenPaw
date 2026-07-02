import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { agentsApi } from "./agents";
import { request } from "../request";

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
});
