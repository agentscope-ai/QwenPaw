import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { advisorModeApi } from "./advisorMode";
import { request } from "../request";

const STATE = {
  enabled: false,
  plan_enabled: true,
  followup_enabled: true,
  on_demand_enabled: true,
  agent_id: "a1",
  teacher_model: { provider_id: "dash", model: "qwen3-max" },
  student_model: null,
};

describe("advisorModeApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("get calls GET /advisor-mode", async () => {
    vi.mocked(request).mockResolvedValue(STATE);
    const result = await advisorModeApi.get();
    expect(request).toHaveBeenCalledWith("/advisor-mode");
    expect(result).toEqual(STATE);
  });

  it("update sends POST /advisor-mode with only the given fields", async () => {
    const resp = { ...STATE, enabled: true };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await advisorModeApi.update({ enabled: true });
    expect(request).toHaveBeenCalledWith("/advisor-mode", {
      method: "POST",
      body: JSON.stringify({ enabled: true }),
    });
    expect(result).toEqual(resp);
  });

  it("update can change follow-up alone", async () => {
    vi.mocked(request).mockResolvedValue({ ...STATE, followup_enabled: false });
    await advisorModeApi.update({ followup_enabled: false });
    expect(request).toHaveBeenCalledWith("/advisor-mode", {
      method: "POST",
      body: JSON.stringify({ followup_enabled: false }),
    });
  });
});
