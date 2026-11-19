import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { SteerContent } from "./steerTimeline";
import { useSteerSender } from "./useSteerSender";
import { useSteerStore } from "../../stores/steerStore";
import { request } from "../../api/request";

vi.mock("../../api/request", async (original) => ({
  ...(await original<typeof import("../../api/request")>()),
  request: vi.fn(),
}));
const status = {
  scope: "agent:session",
  turn_id: "t1",
  can_steer: true,
  receipts: [],
};
beforeEach(() => {
  sessionStorage.clear();
  useSteerStore.setState({ receipts: {}, retry: {}, historySync: {} });
  vi.mocked(request).mockReset();
});
afterEach(() => cleanup());

it("retries the same intent after reload and never delivers it to a newer turn", async () => {
  const content: SteerContent = [
    { type: "text", text: "fix" },
    { type: "file", file_url: "/media/test.txt", file_name: "test.txt" },
  ];
  const posts: Array<{
    turn_id: string;
    client_message_id: string;
    content: SteerContent;
  }> = [];
  let nextTurn = false;
  vi.mocked(request).mockImplementation(async (_url, options) => {
    if (options?.method === "POST") {
      const payload = JSON.parse(String(options.body));
      posts.push(payload);
      if (posts.length === 1) throw new Error("response lost");
      return {
        ...payload,
        status: "accepted",
        user_message_id: "s1",
        append_seq: 1,
        revision: 1,
      } as never;
    }
    return { ...status, turn_id: nextTurn ? "t2" : "t1" } as never;
  });
  const first = renderHook(() => useSteerSender("chat", "agent", true));
  await act(async () => {
    await expect(first.result.current.submit(content)).rejects.toThrow(
      "response lost",
    );
  });
  const id = posts[0].client_message_id;
  expect(useSteerStore.getState().receipts[status.scope][0].status).toBe(
    "unknown",
  );
  first.unmount();
  nextTurn = true;
  const reloaded = renderHook(() => useSteerSender("chat", "agent", true));
  await act(async () => {
    expect(await reloaded.result.current.submit(content)).toBe(true);
  });
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual({
    turn_id: "t1",
    client_message_id: id,
    content,
  });
  expect(reloaded.result.current.hasPending()).toBe(false);
});

it("keeps attachment drafts and cannot clear a new chat after a late acknowledgment", async () => {
  let acknowledge!: (value: unknown) => void;
  vi.mocked(request).mockImplementation(async (_url, options) => {
    if (options?.method === "POST")
      return (await new Promise<unknown>((resolve) => {
        acknowledge = resolve;
      })) as never;
    return status as never;
  });
  const hook = renderHook(({ chat }) => useSteerSender(chat, "agent", true), {
    initialProps: { chat: "A" },
  });
  await act(async () => {
    await expect(hook.result.current.submit([])).rejects.toThrow();
  });
  expect(
    vi.mocked(request).mock.calls.filter(([, o]) => o?.method === "POST"),
  ).toHaveLength(0);
  let pending!: Promise<boolean>;
  await act(async () => {
    pending = hook.result.current.submit([
      { type: "file", file_url: "/media/only.txt", file_name: "only.txt" },
    ]);
    await Promise.resolve();
  });
  hook.rerender({ chat: "B" });
  await act(async () => {
    acknowledge({
      ...status,
      client_message_id: "c",
      content: [{ type: "text", text: "text" }],
      status: "accepted",
      revision: 1,
      append_seq: 1,
      user_message_id: "s",
    });
    expect(await pending).toBe(false);
  });
});

it("stops idle polling, wakes for a run, and retains receipts after settlement", async () => {
  vi.useFakeTimers();
  try {
    const receipt = {
      turn_id: "t1",
      client_message_id: "attachment",
      user_message_id: "s1",
      append_seq: 1,
      revision: 2,
      status: "failed" as const,
      content: [
        {
          type: "file" as const,
          file_url: "/media/test.txt",
          file_name: "test.txt",
        },
      ],
    };
    useSteerStore.getState().hydrateHistory("agent:chat", status.scope, {
      active_turn_id: null,
      needs_sync: false,
      receipts_by_turn: { t1: [receipt] },
    });
    vi.mocked(request).mockResolvedValue({
      ...status,
      needs_sync: false,
      receipts: [receipt],
    });
    const hook = renderHook(
      ({ running }) => useSteerSender("chat", "agent", true, running),
      {
        initialProps: { running: false },
      },
    );
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(request).not.toHaveBeenCalled();
    hook.rerender({ running: true });
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(request).toHaveBeenCalledTimes(1);
    hook.rerender({ running: false });
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    const settledCalls = vi.mocked(request).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(request).toHaveBeenCalledTimes(settledCalls);
    expect(useSteerStore.getState().receipts[status.scope]).toEqual([receipt]);
    hook.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("wakes when a late history page reveals an unsettled attachment", async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(request).mockResolvedValue({ ...status, needs_sync: false });
    const hook = renderHook(() => useSteerSender("chat", "agent", true));
    await act(async () => Promise.resolve());
    const receipt = {
      turn_id: "old-turn",
      client_message_id: "late",
      user_message_id: "s",
      append_seq: 1,
      revision: 1,
      status: "accepted" as const,
      content: [
        {
          type: "file" as const,
          file_url: "/media/late.txt",
          file_name: "late.txt",
        },
      ],
    };
    act(() =>
      useSteerStore.getState().hydrateHistory("agent:chat", status.scope, {
        active_turn_id: null,
        needs_sync: true,
        receipts_by_turn: { "old-turn": [receipt] },
      }),
    );
    vi.mocked(request).mockResolvedValue({
      ...status,
      needs_sync: false,
      receipts: [{ ...receipt, status: "failed", revision: 2 }],
    });
    await act(async () => vi.advanceTimersByTimeAsync(1500));
    expect(vi.mocked(request).mock.lastCall?.[0]).toContain("turn_id=old-turn");
    const settledCalls = vi.mocked(request).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(request).toHaveBeenCalledTimes(settledCalls);
    expect(useSteerStore.getState().receipts[status.scope][0].status).toBe(
      "failed",
    );
    hook.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("settles a missing applied message instead of silently stopping after one read", async () => {
  vi.useFakeTimers();
  try {
    const receipt = {
      turn_id: "t1",
      client_message_id: "missing",
      user_message_id: "s1",
      append_seq: 1,
      revision: 2,
      status: "applied" as const,
      content: [{ type: "text" as const, text: "retained input" }],
    };
    vi.mocked(request).mockImplementation(
      async () =>
        ({
          ...status,
          needs_sync: false,
          receipts: [{ ...receipt }],
        }) as never,
    );
    const hook = renderHook(() => useSteerSender("chat", "agent", true));
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(request).toHaveBeenCalledTimes(2);
    expect(useSteerStore.getState().receipts[status.scope][0].status).toBe(
      "sync_failed",
    );
    hook.unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("does not clear a newer local submission when an older poll returns", async () => {
  let resolve!: (value: unknown) => void;
  const receipt = {
    turn_id: "t1",
    client_message_id: "old",
    user_message_id: "s1",
    append_seq: 1,
    revision: 1,
    status: "accepted" as const,
    content: [{ type: "text" as const, text: "old" }],
  };
  const key = "qwenpaw-steer:agent:chat";
  sessionStorage.setItem(key, JSON.stringify({ scope: status.scope, receipt }));
  vi.mocked(request).mockImplementation(
    async () =>
      (await new Promise<unknown>((done) => {
        resolve = done;
      })) as never,
  );
  const hook = renderHook(() => useSteerSender("chat", "agent", true));
  sessionStorage.setItem(
    key,
    JSON.stringify({
      scope: status.scope,
      receipt: { ...receipt, client_message_id: "new", status: "submitting" },
    }),
  );
  await act(async () =>
    resolve({
      ...status,
      needs_sync: false,
      receipts: [{ ...receipt, status: "failed", revision: 2 }],
    }),
  );
  expect(
    JSON.parse(sessionStorage.getItem(key)!).receipt.client_message_id,
  ).toBe("new");
  hook.unmount();
});
