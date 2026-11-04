import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useChannels } from "./useChannels";

// Mock api（default export）
vi.mock("../../../api", () => ({
  default: {
    listChannels: vi.fn(),
    listChannelTypes: vi.fn(),
    listChannelSchemas: vi.fn(),
  },
}));

// Mock agentStore
vi.mock("../../../stores/agentStore", async () => {
  const { create } = await import("zustand");
  return { useAgentStore: create(() => ({ selectedAgent: "agent-1" })) };
});

import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import type { ChannelRequestScope } from "../../../api/modules/channel";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("useChannels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentStore.setState({ selectedAgent: "agent-1" });
    (api.listChannels as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (api.listChannelSchemas as ReturnType<typeof vi.fn>).mockResolvedValue({});
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
    const scope = { agentId: "agent-1", signal: expect.any(AbortSignal) };
    expect(api.listChannels).toHaveBeenCalledWith(scope);
    expect(api.listChannelTypes).toHaveBeenCalledWith(scope);
    expect(api.listChannelSchemas).toHaveBeenCalledWith(scope);
    expect(vi.mocked(api.listChannels).mock.calls[0][0]).toBe(
      vi.mocked(api.listChannelSchemas).mock.calls[0][0],
    );
  });

  it("exposes a load error and recovers through a stable retry callback", async () => {
    const failure = new Error("offline");
    (api.listChannels as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce({ console: { enabled: false } });

    const { result } = renderHook(() => useChannels());
    const retry = result.current.fetchChannels;
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(failure);
    expect(result.current.ready).toBe(false);
    expect(result.current.channels).toEqual({});

    await act(async () => {
      await retry();
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.fetchChannels).toBe(retry);
    expect(result.current.error).toBeNull();
    expect(result.current.channels).toEqual({ console: { enabled: false } });
  });

  it("keeps the new agent data when the previous request settles late", async () => {
    const agentA = deferred<Record<string, Record<string, unknown>>>();
    const agentB = deferred<Record<string, Record<string, unknown>>>();
    (api.listChannels as ReturnType<typeof vi.fn>).mockImplementation(
      ({ agentId }: ChannelRequestScope) =>
        agentId === "agent-1" ? agentA.promise : agentB.promise,
    );
    (api.listChannelTypes as ReturnType<typeof vi.fn>).mockImplementation(
      async ({ agentId }: ChannelRequestScope) =>
        agentId === "agent-1" ? ["console"] : ["dingtalk"],
    );

    const { result, rerender } = renderHook(() => useChannels());
    act(() => useAgentStore.setState({ selectedAgent: "agent-2" }));
    rerender();
    expect(result.current.channels).toEqual({});
    expect(result.current.ready).toBe(false);

    await act(async () => {
      agentB.resolve({ dingtalk: { enabled: true } });
      await agentB.promise;
    });
    expect(result.current.channels).toEqual({
      dingtalk: { enabled: true },
    });
    expect(result.current.ready).toBe(true);

    await act(async () => {
      agentA.resolve({ console: { enabled: true } });
      await agentA.promise;
    });
    expect(result.current.channels).toEqual({
      dingtalk: { enabled: true },
    });
    expect(result.current.error).toBeNull();
  });

  it("ignores a late failure from the previous agent", async () => {
    const agentA = deferred<Record<string, Record<string, unknown>>>();
    const agentB = deferred<Record<string, Record<string, unknown>>>();
    (api.listChannels as ReturnType<typeof vi.fn>).mockImplementation(
      ({ agentId }: ChannelRequestScope) =>
        agentId === "agent-1" ? agentA.promise : agentB.promise,
    );

    const { result, rerender } = renderHook(() => useChannels());
    act(() => useAgentStore.setState({ selectedAgent: "agent-2" }));
    rerender();

    await act(async () => {
      agentB.resolve({ dingtalk: { enabled: true } });
      await agentB.promise;
    });
    expect(result.current.ready).toBe(true);

    await act(async () => {
      agentA.reject(new Error("agent-a offline"));
      await agentA.promise.catch(() => undefined);
    });
    expect(result.current.channels).toEqual({
      dingtalk: { enabled: true },
    });
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("rejects stale owner updates without changing current channels", async () => {
    const { result, rerender } = renderHook(() => useChannels());
    await waitFor(() => expect(result.current.ready).toBe(true));
    const staleOwner = result.current.agentId;
    const guardedUpdate = result.current.setChannels;

    act(() => useAgentStore.setState({ selectedAgent: "agent-2" }));
    rerender();
    expect(guardedUpdate(staleOwner, { console: { enabled: true } })).toBe(
      false,
    );
    expect(result.current.channels).toEqual({});
  });

  it("loads core config before the optional plugin catalogue and includes offline channels", async () => {
    const catalogue = deferred<Record<string, unknown>>();
    vi.mocked(api.listChannels).mockResolvedValue({
      "configured-plugin": { enabled: false },
    } as never);
    vi.mocked(api.listChannelTypes).mockResolvedValue(["console"]);
    vi.mocked(api.listChannelSchemas).mockReturnValue(
      catalogue.promise as never,
    );
    const { result } = renderHook(() => useChannels());

    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.loading).toBe(false);
    expect(result.current.schemasLoading).toBe(true);
    expect(result.current.orderedKeys).toEqual([
      "console",
      "configured-plugin",
    ]);

    await act(async () => {
      catalogue.resolve({
        "offline-plugin": {
          plugin_id: "offline-plugin",
          availability: "not_installed",
          repair: {
            action: "install",
            plugin_id: "offline-plugin",
            source: "hub:offline-plugin",
          },
          config_fields: [],
        },
      });
      await catalogue.promise;
    });
    expect(result.current.schemasLoading).toBe(false);
    expect(result.current.ready).toBe(true);
    expect(result.current.orderedKeys).toEqual([
      "console",
      "configured-plugin",
      "offline-plugin",
    ]);
    expect(result.current.channelSchemas["offline-plugin"]).toMatchObject({
      availability: "not_installed",
      repair: { action: "install" },
    });
  });

  it("keeps core data usable when the optional schema request fails", async () => {
    vi.mocked(api.listChannels).mockResolvedValue({
      console: { enabled: true },
    } as never);
    vi.mocked(api.listChannelSchemas).mockRejectedValue(
      new Error("plugins offline"),
    );
    const { result } = renderHook(() => useChannels());

    await waitFor(() => expect(result.current.schemasLoading).toBe(false));
    expect(result.current.ready).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.channels).toEqual({ console: { enabled: true } });
    expect(result.current.channelSchemas).toEqual({});
  });

  it("refreshes plugin schemas without refetching or clearing the loaded config", async () => {
    vi.mocked(api.listChannels).mockResolvedValue({
      console: { enabled: true },
    } as never);
    const { result } = renderHook(() => useChannels());
    await waitFor(() => expect(result.current.schemasLoading).toBe(false));
    const catalogue = deferred<Record<string, unknown>>();
    vi.mocked(api.listChannelSchemas).mockReturnValueOnce(
      catalogue.promise as never,
    );
    let refresh!: Promise<void>;
    act(() => {
      refresh = result.current.fetchChannels(true);
    });

    expect(result.current.channels).toEqual({ console: { enabled: true } });
    expect(result.current.ready).toBe(true);
    expect(result.current.loading).toBe(false);
    expect(result.current.schemasLoading).toBe(true);
    expect(api.listChannels).toHaveBeenCalledOnce();
    expect(api.listChannelTypes).toHaveBeenCalledOnce();
    await act(async () => {
      catalogue.resolve({});
      await refresh;
    });
    expect(result.current.schemasLoading).toBe(false);
  });

  it("invalidates requests across a batched A-B-A store transition", async () => {
    const stale = deferred<Record<string, Record<string, unknown>>>();
    const fresh = deferred<Record<string, Record<string, unknown>>>();
    vi.mocked(api.listChannels)
      .mockReturnValueOnce(stale.promise as never)
      .mockResolvedValueOnce({} as never)
      .mockReturnValueOnce(fresh.promise as never);
    const { result } = renderHook(() => useChannels());
    const firstScope = vi.mocked(api.listChannels).mock
      .calls[0][0] as ChannelRequestScope;
    act(() => {
      useAgentStore.setState({ selectedAgent: "agent-2" });
      useAgentStore.setState({ selectedAgent: "agent-1" });
    });
    expect(firstScope.signal?.aborted).toBe(true);
    expect(api.listChannels).toHaveBeenCalledTimes(3);
    expect(result.current.ready).toBe(false);

    await act(async () => {
      fresh.resolve({ console: { enabled: false } });
      await fresh.promise;
    });
    expect(result.current.ready).toBe(true);
    await act(async () => {
      stale.resolve({ console: { enabled: true } });
      await stale.promise;
    });
    expect(result.current.channels).toEqual({ console: { enabled: false } });
    expect(result.current.error).toBeNull();
  });

  it("aborts in-flight reads when the owner unmounts", () => {
    vi.mocked(api.listChannels).mockReturnValue(new Promise(() => {}) as never);
    const { unmount } = renderHook(() => useChannels());
    const scope = vi.mocked(api.listChannels).mock
      .calls[0][0] as ChannelRequestScope;
    expect(scope.signal?.aborted).toBe(false);
    unmount();
    expect(scope.signal?.aborted).toBe(true);
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
