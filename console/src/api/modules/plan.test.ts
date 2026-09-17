import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));

import { request } from "../request";
import { planApi, type PlanConfigResponse } from "./plan";

describe("planApi runtime config targeting", () => {
  const config: PlanConfigResponse = {
    enabled: true,
    auto_enabled: true,
    auto_execute: false,
    complexity_threshold: "medium",
  };

  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(config);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("routes plan config reads and writes to the explicit governance target", async () => {
    const context = {
      agentId: "governed-agent",
      governance: true,
    };

    await planApi.getPlanConfig(context);
    await planApi.updatePlanConfig(config, context);

    expect(request).toHaveBeenNthCalledWith(1, "/plan/config", {
      headers: {
        "X-Agent-Id": "governed-agent",
        "X-Agent-Governance": "runtime-config",
      },
    });
    expect(request).toHaveBeenNthCalledWith(2, "/plan/config", {
      method: "PUT",
      body: JSON.stringify(config),
      headers: {
        "X-Agent-Id": "governed-agent",
        "X-Agent-Governance": "runtime-config",
      },
    });
  });

  it("does not attach runtime governance to session plan operations", async () => {
    await planApi.getCurrentPlan("session-1");

    expect(request).toHaveBeenCalledWith("/plan/current?session_id=session-1");
  });
});
