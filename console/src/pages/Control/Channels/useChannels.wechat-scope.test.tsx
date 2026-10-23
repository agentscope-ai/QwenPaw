import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAgentStore } from "../../../stores/agentStore";
import { useChannels } from "./useChannels";

type PendingList = {
  agentId: string | null;
  resolve: (response: Response) => void;
};
const lists: PendingList[] = [];

function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  lists.length = 0;
  useAgentStore.setState({ selectedAgent: "A" });
  vi.stubGlobal(
    "fetch",
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input), "https://console.test").pathname;
      if (path.endsWith("/config/channels")) {
        return new Promise<Response>((resolve) => {
          lists.push({
            agentId: new Headers(init.headers).get("X-Agent-Id"),
            resolve,
          });
        });
      }
      if (path.endsWith("/types")) return json(["wechat"]);
      if (path.endsWith("/schemas")) return json({});
      throw new Error("Unexpected network boundary: " + path);
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  localStorage.clear();
});

it("keeps B's actual list source when the earlier A GET resolves last", async () => {
  const view = renderHook(() => useChannels());
  expect(lists).toHaveLength(1);
  expect(lists[0].agentId).toBe("A");
  act(() => useAgentStore.setState({ selectedAgent: "B" }));
  expect(lists).toHaveLength(2);
  expect(lists[1].agentId).toBe("B");
  const configB = { wechat: { enabled: false, bot_token: "B-only" } };
  await act(async () => lists[1].resolve(json(configB)));
  expect(view.result.current.channels).toEqual(configB);
  expect(view.result.current.loading).toBe(false);
  // The fetch boundary deliberately allows a late response even if aborted:
  // cancellation alone cannot replace the hook's generation/scope fence.
  await act(async () => {
    lists[0].resolve(
      json({ wechat: { enabled: false, bot_token: "stale-A" } }),
    );
  });
  expect(useAgentStore.getState().selectedAgent).toBe("B");
  expect(view.result.current.channels).toEqual(configB);
});

it.each(["types", "schemas"])(
  "fences late A %s and clears old source while B is loading",
  async (kind) => {
    const waiting: { agent: string | null; resolve: (r: Response) => void }[] =
      [];
    vi.stubGlobal(
      "fetch",
      async (input: string | URL | Request, init: RequestInit = {}) => {
        const path = new URL(String(input), "https://console.test").pathname;
        const agent = new Headers(init.headers).get("X-Agent-Id");
        if (path.endsWith("/" + kind)) {
          return new Promise<Response>((resolve) =>
            waiting.push({ agent, resolve }),
          );
        }
        if (path.endsWith("/types")) return json(["wechat"]);
        if (path.endsWith("/schemas")) return json({});
        return json({ wechat: { enabled: false, bot_token: agent } });
      },
    );
    const view = renderHook(() => useChannels());
    await act(async () => {});
    expect(waiting[0].agent).toBe("A");
    act(() => useAgentStore.setState({ selectedAgent: "B" }));
    // A's saved form source cannot remain visible during B's request.
    expect(view.result.current.channels).toEqual({});
    expect(view.result.current.channelTypes).toEqual([]);
    expect(view.result.current.channelSchemas).toEqual({});
    expect(view.result.current.loading).toBe(true);
    await act(async () => {});
    expect(waiting[1].agent).toBe("B");
    const resultB =
      kind === "types"
        ? ["wechat", "B_type"]
        : { B_schema: { label: "B", config_fields: [] } };
    await act(async () => waiting[1].resolve(json(resultB)));
    const stale =
      kind === "types"
        ? ["A_type"]
        : { A_schema: { label: "A", config_fields: [] } };
    await act(async () => waiting[0].resolve(json(stale)));
    expect(view.result.current.channels.wechat.bot_token).toBe("B");
    expect(
      kind === "types"
        ? view.result.current.channelTypes
        : view.result.current.channelSchemas,
    ).toEqual(resultB);
    expect(view.result.current.loading).toBe(false);
  },
);

it("fences batched ABA and same-scope refresh generations", async () => {
  const view = renderHook(() => useChannels());
  act(() => {
    useAgentStore.setState({ selectedAgent: "B" });
    useAgentStore.setState({ selectedAgent: "A" });
  });
  expect(lists.map((row) => row.agentId)).toEqual(["A", "B", "A"]);
  await act(async () =>
    lists[2].resolve(json({ wechat: { bot_token: "fresh-A" } })),
  );
  await act(async () => {
    lists[0].resolve(json({ wechat: { bot_token: "old-A" } }));
    lists[1].resolve(json({ wechat: { bot_token: "B" } }));
  });
  expect(view.result.current.channels.wechat.bot_token).toBe("fresh-A");
  let refresh!: Promise<void>;
  act(() => {
    refresh = view.result.current.fetchChannels();
  });
  expect(lists[3].agentId).toBe("A");
  await act(async () => {
    lists[3].resolve(json({ wechat: { bot_token: "refreshed-A" } }));
    await refresh;
  });
  expect(view.result.current.channels.wechat.bot_token).toBe("refreshed-A");
  expect(view.result.current.loading).toBe(false);
});
