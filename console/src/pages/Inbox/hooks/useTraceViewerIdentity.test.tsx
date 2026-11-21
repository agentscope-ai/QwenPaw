import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import api from "../../../api";
import { useAuthStore } from "../../../stores/authStore";
import { clearAccessSession } from "../../../api/authSession";
import type { PushMessage } from "../types";
import { useTraceViewer } from "./useTraceViewer";

vi.mock("../../../api", () => ({ default: { getInboxTrace: vi.fn() } }));
vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function item(id: string): PushMessage {
  return {
    id,
    channelType: "memory",
    channelName: "test memory",
    title: `private-${id}`,
    sender: { userId: "fixture-agent", username: "fixture" },
    read: true,
    content: `private-${id}`,
    createdAt: new Date(),
    metadata: { payload: { run_id: id } },
  };
}
function trace(text: string) {
  return { events: [{ at: 1, event: { content: [{ type: "text", text }] } }] };
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "account-a", platform_role: "member" } as never,
  });
});
afterEach(cleanup);

it("does not keep account A's selected private trace after switching to B", async () => {
  vi.mocked(api.getInboxTrace).mockResolvedValue(
    trace("private trace A") as never,
  );
  const { result, rerender } = renderHook(() => useTraceViewer(vi.fn()));
  await act(async () => {
    result.current.openMessageDetail(item("a"));
  });
  expect(result.current.traceEvents[0]?.traceText).toBe("private trace A");
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
  rerender();
  expect(result.current.detailOpen).toBe(false);
  expect(result.current.selectedMessage).toBeNull();
  expect(result.current.traceEvents).toEqual([]);
});

it("does not restore A's fallback body when an old identity request rejects", async () => {
  const pending = deferred<never>();
  vi.mocked(api.getInboxTrace).mockReturnValue(pending.promise);
  const { result, rerender } = renderHook(() => useTraceViewer(vi.fn()));
  act(() => {
    result.current.openMessageDetail(item("a"));
  });
  act(() => {
    useAuthStore.setState({
      user: { id: "account-b", platform_role: "member" } as never,
    });
  });
  rerender();
  await act(async () => {
    pending.reject(new DOMException("Identity changed", "AbortError"));
  });
  expect(result.current.traceEvents).toEqual([]);
  expect(result.current.detailOpen).toBe(false);
});

it("does not let a slower earlier trace replace the newly selected message", async () => {
  const first = deferred<ReturnType<typeof trace>>();
  const second = deferred<ReturnType<typeof trace>>();
  vi.mocked(api.getInboxTrace)
    .mockReturnValueOnce(first.promise as never)
    .mockReturnValueOnce(second.promise as never);
  const { result } = renderHook(() => useTraceViewer(vi.fn()));
  act(() => {
    result.current.openMessageDetail(item("a"));
  });
  act(() => {
    result.current.openMessageDetail(item("b"));
  });
  await act(async () => {
    second.resolve(trace("latest B"));
  });
  expect(result.current.traceEvents[0]?.traceText).toBe("latest B");
  await act(async () => {
    first.resolve(trace("stale A"));
  });
  expect(result.current.selectedMessage?.id).toBe("b");
  expect(result.current.traceEvents[0]?.traceText).toBe("latest B");
});

it("does not refill trace data after closing its modal", async () => {
  const pending = deferred<ReturnType<typeof trace>>();
  vi.mocked(api.getInboxTrace).mockReturnValue(pending.promise as never);
  const { result } = renderHook(() => useTraceViewer(vi.fn()));
  act(() => {
    result.current.openMessageDetail(item("a"));
  });
  act(() => {
    result.current.closeDetail();
  });
  await act(async () => {
    pending.resolve(trace("closed A"));
  });
  expect(result.current.detailOpen).toBe(false);
  expect(result.current.selectedMessage).toBeNull();
  expect(result.current.traceEvents).toEqual([]);
});

it("preserves the current user's trace during a token refresh", async () => {
  vi.mocked(api.getInboxTrace).mockResolvedValue(
    trace("current trace") as never,
  );
  const { result } = renderHook(() => useTraceViewer(vi.fn()));
  await act(async () => {
    result.current.openMessageDetail(item("a"));
  });
  act(() => {
    useAuthStore.setState({ accessToken: "renewed-token" });
  });
  expect(result.current.detailOpen).toBe(true);
  expect(result.current.traceEvents[0]?.traceText).toBe("current trace");
});

it("clears private detail when the session generation changes", async () => {
  vi.mocked(api.getInboxTrace).mockResolvedValue(
    trace("previous session") as never,
  );
  const { result } = renderHook(() => useTraceViewer(vi.fn()));
  await act(async () => {
    result.current.openMessageDetail(item("a"));
  });
  act(() => {
    clearAccessSession(false);
  });
  expect(result.current.detailOpen).toBe(false);
  expect(result.current.selectedMessage).toBeNull();
  expect(result.current.traceEvents).toEqual([]);
});
