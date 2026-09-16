import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { App } from "antd";
import { afterEach, expect, it, vi } from "vitest";
import { useMarketInstall } from "./useMarketInstall";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import type { MarketResult } from "@/api/modules/market";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("does not install the next queued market skill after an identity switch", async () => {
  useAuthStore.setState({
    phase: "authenticated",
    mode: "multi_user",
    user: { id: "alice", platform_role: "member" } as never,
  });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [
      { id: "a", enabled: true, access_role: "owner", can_edit: true },
    ] as never,
  });
  let finish!: (value: Response) => void;
  const fetch = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          finish = r;
        }),
    )
    .mockResolvedValue(
      new Response('{"task_id":"new-session-task"}', {
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(
    () => useMarketInstall({ selectedAgent: "a" }),
    { wrapper: ({ children }) => <App>{children}</App> },
  );
  const items = ["one", "two"].map(
    (slug) =>
      ({
        source: "hub",
        slug,
        name: slug,
        source_url: `https://example.invalid/${slug}.zip`,
      }) as MarketResult,
  );
  act(() => {
    result.current.enqueue(items, "workspace");
  });
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", platform_role: "member" } as never,
    }),
  );
  await act(async () =>
    finish(
      new Response('{"task_id":"old-session-task"}', {
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(result.current.queue).toEqual([]);
});
