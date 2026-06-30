import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { codingModeApi } from "./codingMode";
import { request } from "../request";

describe("codingModeApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("get calls GET /coding-mode", async () => {
    const state = { enabled: false, project_dir: null, agent_id: "a1" };
    vi.mocked(request).mockResolvedValue(state);
    const result = await codingModeApi.get();
    expect(request).toHaveBeenCalledWith("/coding-mode");
    expect(result).toEqual(state);
  });

  it("toggle sends POST /coding-mode with enabled flag", async () => {
    const resp = { enabled: true, agent_id: "a1" };
    vi.mocked(request).mockResolvedValue(resp);
    const result = await codingModeApi.toggle(true);
    expect(request).toHaveBeenCalledWith("/coding-mode", {
      method: "POST",
      body: JSON.stringify({ enabled: true }),
    });
    expect(result).toEqual(resp);
  });
});
