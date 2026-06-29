import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// 顶层 mock（Vitest 会提升这些），使用 doMock 以兼容 resetModules
vi.mock("../api/modules/workspace", () => ({
  workspaceApi: { getWatchUrl: vi.fn().mockReturnValue("http://test/watch") },
}));
vi.mock("../api/authHeaders", () => ({
  buildAuthHeaders: vi.fn().mockReturnValue({}),
}));

// SSE mock 辅助函数：创建可手动推送数据的 ReadableStream
function makeSseMock() {
  const encoder = new TextEncoder();
  let ctrl: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      ctrl = c;
    },
  });

  const mockFetch = vi.fn().mockResolvedValue({
    ok: true,
    body: stream,
  } as unknown as Response);

  const push = (line: string) => {
    ctrl.enqueue(encoder.encode(line + "\n"));
  };
  const close = () => ctrl.close();

  return { mockFetch, push, close };
}

describe("useWorkspaceWatch — message handling", () => {
  let useWorkspaceWatch: typeof import("./useWorkspaceWatch").useWorkspaceWatch;

  beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules();

    vi.doMock("../api/modules/workspace", () => ({
      workspaceApi: {
        getWatchUrl: vi.fn().mockReturnValue("http://test/watch"),
      },
    }));
    vi.doMock("../api/authHeaders", () => ({
      buildAuthHeaders: vi.fn().mockReturnValue({}),
    }));

    ({ useWorkspaceWatch } = await import("./useWorkspaceWatch"));
  });

  afterEach(() => {
    // 恢复原始 fetch（防止 mock 泄漏）
    vi.restoreAllMocks();
  });

  // ─── 测试 3：解析 SSE data 行并调用 callback ─────────────────────────────
  it("解析 SSE data 行并调用 callback（type=file_change）", async () => {
    const { mockFetch, push, close } = makeSseMock();
    vi.stubGlobal("fetch", mockFetch);

    const onFileChange = vi.fn();
    const { unmount } = renderHook(() => useWorkspaceWatch(onFileChange, true));

    // 等 fetch 被调用
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());

    // 推送 SSE 数据
    const payload = JSON.stringify({
      type: "file_change",
      events: [{ change: "added", path: "/foo/bar.ts" }],
    });

    act(() => {
      push(`data: ${payload}`);
    });

    await waitFor(() => {
      expect(onFileChange).toHaveBeenCalledWith([
        { change: "added", path: "/foo/bar.ts" },
      ]);
    });

    close();
    unmount();
  });

  // ─── 测试 4：忽略非 data: 开头的行 ──────────────────────────────────────
  it("忽略非 data: 开头的行", async () => {
    const { mockFetch, push, close } = makeSseMock();
    vi.stubGlobal("fetch", mockFetch);

    const onFileChange = vi.fn();
    const { unmount } = renderHook(() => useWorkspaceWatch(onFileChange, true));

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());

    act(() => {
      push("event: file_change");
      push(": comment line");
      push("id: 123");
    });

    // 等待一个 tick，确保这些行被处理
    await act(async () => {});

    expect(onFileChange).not.toHaveBeenCalled();

    close();
    unmount();
  });

  // ─── 测试 5：忽略 type !== "file_change" 的消息 ───────────────────────────
  it("忽略 type !== file_change 的消息", async () => {
    const { mockFetch, push, close } = makeSseMock();
    vi.stubGlobal("fetch", mockFetch);

    const onFileChange = vi.fn();
    const { unmount } = renderHook(() => useWorkspaceWatch(onFileChange, true));

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());

    const payload = JSON.stringify({
      type: "ping",
      events: [{ change: "added", path: "/foo/bar.ts" }],
    });

    act(() => {
      push(`data: ${payload}`);
    });

    await act(async () => {});

    expect(onFileChange).not.toHaveBeenCalled();

    close();
    unmount();
  });

  // ─── 测试 6：unmount 后从 _listeners 移除，第二个 hook 仍然能收到事件 ────
  it("unmount 后从 _listeners 移除，第二个 hook 仍然能收到事件", async () => {
    const { mockFetch, push, close } = makeSseMock();
    vi.stubGlobal("fetch", mockFetch);

    const cb1 = vi.fn();
    const cb2 = vi.fn();

    const { unmount: unmount1 } = renderHook(() =>
      useWorkspaceWatch(cb1, true),
    );
    const { unmount: unmount2 } = renderHook(() =>
      useWorkspaceWatch(cb2, true),
    );

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());

    // 先 unmount 第一个 hook
    act(() => {
      unmount1();
    });

    // 发送一个事件
    const payload = JSON.stringify({
      type: "file_change",
      events: [{ change: "modified", path: "/x.ts" }],
    });

    act(() => {
      push(`data: ${payload}`);
    });

    await waitFor(() => {
      // cb2 应该收到事件
      expect(cb2).toHaveBeenCalledWith([{ change: "modified", path: "/x.ts" }]);
    });

    // cb1 不应该收到（已 unmount）
    expect(cb1).not.toHaveBeenCalled();

    close();
    unmount2();
  });
});
