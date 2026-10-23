import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

vi.mock("../../../api", () => ({
  default: {
    listChannels: vi.fn().mockResolvedValue({
      console: { isBuiltin: true },
      removed_plugin: { isBuiltin: false, token: "saved" },
    }),
    listChannelTypes: vi.fn().mockResolvedValue(["console"]),
    listChannelSchemas: vi.fn().mockResolvedValue({
      feishu: { availability: "missing_code", config_fields: [] },
      dingtalk: { availability: "disabled", config_fields: [] },
    }),
  },
}));
vi.mock("../../../stores/agentStore", async () => {
  const { create } = await import("zustand");
  return { useAgentStore: create(() => ({ selectedAgent: "c6-agent" })) };
});

import { useChannels } from "./useChannels";

describe("C6 channel configuration catalog", () => {
  it("unions runtime types, saved settings and dormant schemas", async () => {
    const { result } = renderHook(() => useChannels());
    await waitFor(() =>
      expect(result.current.channelSchemas.feishu).toBeTruthy(),
    );
    expect(result.current.orderedKeys).toEqual([
      "console",
      "dingtalk",
      "feishu",
      "removed_plugin",
    ]);
    expect(result.current.isBuiltin("feishu")).toBe(false);
  });
});
