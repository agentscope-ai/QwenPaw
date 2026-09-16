import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useChannels } from "./useChannels";

// Mock api（default export）
vi.mock("../../../api", () => ({
  default: {
    listChannels: vi.fn(),
    listChannelTypes: vi.fn(),
    listUserChannelBindings: vi.fn(),
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
    (api.listUserChannelBindings as ReturnType<typeof vi.fn>).mockResolvedValue(
      [],
    );
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

  it("个人绑定模式只读取当前用户绑定，不读取智能体频道配置", async () => {
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
      "console",
      "telegram",
    ]);
    (
      api.listUserChannelBindings as ReturnType<typeof vi.fn>
    ).mockResolvedValue([
      {
        id: "binding-1",
        channel_type: "telegram",
        display_name: "我的 Telegram",
        enabled: true,
        config: { bot_prefix: "mine" },
        configured_secret_fields: ["bot_token"],
      },
    ]);

    const { result } = renderHook(() => useChannels("user"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(api.listChannels).not.toHaveBeenCalled();
    expect(api.listUserChannelBindings).toHaveBeenCalledWith("agent-1");
    expect(result.current.channels.telegram).toEqual({
      enabled: true,
      bot_prefix: "mine",
      display_name: "我的 Telegram",
      isBuiltin: true,
      bindingId: "binding-1",
      configuredSecretFields: ["bot_token"],
    });
    expect(result.current.channels.console).toEqual({
      enabled: false,
      bot_prefix: "",
      display_name: "",
      isBuiltin: true,
      configuredSecretFields: [],
    });
  });

  it("切换到个人绑定后忽略较晚返回的旧视图请求", async () => {
    let resolveAgentChannels: (
      value: Record<string, Record<string, unknown>>,
    ) => void = () => {};
    const agentChannels = new Promise<
      Record<string, Record<string, unknown>>
    >((resolve) => {
      resolveAgentChannels = resolve;
    });
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
      "telegram",
    ]);
    (api.listChannels as ReturnType<typeof vi.fn>).mockReturnValue(
      agentChannels,
    );
    (
      api.listUserChannelBindings as ReturnType<typeof vi.fn>
    ).mockResolvedValue([
      {
        id: "binding-new",
        channel_type: "telegram",
        display_name: "我的 Telegram",
        enabled: false,
        config: { bot_prefix: "mine" },
        configured_secret_fields: ["bot_token"],
      },
    ]);

    const { result, rerender } = renderHook(
      ({ mode }: { mode: "agent" | "user" }) => useChannels(mode),
      { initialProps: { mode: "agent" as "agent" | "user" } },
    );

    rerender({ mode: "user" as const });
    await waitFor(() => {
      expect(result.current.channels.telegram?.bot_prefix).toBe("mine");
    });

    resolveAgentChannels({ telegram: { bot_prefix: "stale-agent" } });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(result.current.channels.telegram?.bot_prefix).toBe("mine");
  });
});
