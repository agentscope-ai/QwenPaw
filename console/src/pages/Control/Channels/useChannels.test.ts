import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useChannels } from "./useChannels";

// Mock api（default export）
vi.mock("../../../api", () => ({
  default: {
    listChannels: vi.fn(),
    listChannelTypes: vi.fn(),
  },
}));

// Mock agentStore
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({ selectedAgent: "agent-1" })),
}));

import api from "../../../api";

describe("useChannels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  });

  it("初始 loading=true，fetch 成功后 loading=false", async () => {
    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const { result } = renderHook(() => useChannels());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
  });

  it("fetchChannels 调用后设置 channels 和 channelTypes", async () => {
    const mockChannels = {
      console: { isBuiltin: true },
      dingtalk: { isBuiltin: true },
    };
    const mockTypes = ["console", "dingtalk"];

    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockChannels,
    );
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockTypes,
    );

    const { result } = renderHook(() => useChannels());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.channels).toEqual(mockChannels);
    expect(result.current.channelTypes).toEqual(mockTypes);
  });

  it("orderedKeys 按 builtinOrder 排序：builtin 在前，custom 在后", async () => {
    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
      "dingtalk",
      "my-custom",
      "console",
    ]);

    const { result } = renderHook(() => useChannels());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.orderedKeys).toEqual([
      "console",
      "dingtalk",
      "my-custom",
    ]);
  });

  it("orderedKeys 中不在 builtinOrder 的 key 出现在末尾", async () => {
    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
      "alpha-custom",
      "feishu",
      "beta-custom",
      "telegram",
    ]);

    const { result } = renderHook(() => useChannels());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const keys = result.current.orderedKeys;
    const builtinKeys = ["feishu", "telegram"];
    const customKeys = ["alpha-custom", "beta-custom"];

    // builtin keys 全部出现在 custom keys 之前
    const lastBuiltinIndex = Math.max(
      ...builtinKeys.map((k) => keys.indexOf(k)),
    );
    const firstCustomIndex = Math.min(
      ...customKeys.map((k) => keys.indexOf(k)),
    );

    expect(lastBuiltinIndex).toBeLessThan(firstCustomIndex);
    // custom keys 都在末尾
    expect(keys.slice(-customKeys.length).sort()).toEqual(customKeys.sort());
  });

  it("isBuiltin 返回 true 当 channels[key].isBuiltin === true", async () => {
    const mockChannels = {
      console: { isBuiltin: true },
      dingtalk: { isBuiltin: false },
    };

    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockChannels,
    );
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
      "console",
      "dingtalk",
    ]);

    const { result } = renderHook(() => useChannels());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.isBuiltin("console")).toBe(true);
  });

  it("isBuiltin 返回 false 当 key 不存在或 isBuiltin === false", async () => {
    const mockChannels = {
      dingtalk: { isBuiltin: false },
      feishu: { isBuiltin: true },
    };

    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockChannels,
    );
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
      "dingtalk",
      "feishu",
    ]);

    const { result } = renderHook(() => useChannels());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.isBuiltin("dingtalk")).toBe(false);
    expect(result.current.isBuiltin("non-existent-key")).toBe(false);
  });
});
