import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { channelApi } from "../../../../api/modules/channel";
import { useAgentStore } from "../../../../stores/agentStore";
import { useChannelQrcode } from "./useChannelQrcode";

type FetchRow = { url: string; headers: Headers; method: string };
const rows: FetchRow[] = [];
const successes: unknown[][] = [];
const errors: string[] = [];
const credentials = { bot_token: "local-token-A", base_url: "https://wx.test" };
const qr = {
  qrcode_img: "data:image/png;base64,local",
  poll_token: "opaque-A",
};
let platform: (url: string) => Promise<Response>;

function json(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function useWechat(agentId: string) {
  return useChannelQrcode({
    channel: "wechat",
    agentId,
    successStatus: "confirmed",
    successCredentialKey: "bot_token",
    onSuccess: (...args) => successes.push(args),
    onError: (error) => errors.push(error),
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  rows.length = successes.length = errors.length = 0;
  sessionStorage.setItem(
    "qwenpaw-agent-storage",
    JSON.stringify({ state: { selectedAgent: "B" } }),
  );
  platform = async (url) =>
    json(
      url.includes("/status?") ? { status: "waiting", credentials: {} } : qr,
    );
  vi.stubGlobal(
    "fetch",
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = String(input);
      rows.push({
        url,
        headers: new Headers(init.headers),
        method: init.method || "GET",
      });
      return platform(url);
    },
  );
});

afterEach(async () => {
  cleanup();
  await act(async () => {});
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("WeChat scope through the real API and request serializer", () => {
  it("fences a confirmed poll across a real store ABA batched into one render", async () => {
    useAgentStore.setState({ selectedAgent: "A" });
    const pending = deferred<Response>();
    platform = async (url) =>
      url.includes("/status?") ? pending.promise : json(qr);
    const view = renderHook(() => {
      const { selectedAgent } = useAgentStore();
      return useWechat(selectedAgent);
    });
    await act(async () => {
      await view.result.current.fetchQrcode();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(rows.filter((row) => row.url.includes("/status?"))).toHaveLength(1);
    act(() => {
      useAgentStore.setState({ selectedAgent: "B" });
      useAgentStore.setState({ selectedAgent: "A" });
    });
    await act(async () =>
      pending.resolve(json({ status: "confirmed", credentials })),
    );
    expect.soft(successes).toEqual([]);
    expect.soft(view.result.current.qrcodeImg).toBe("");
    const cancelled = rows.filter((row) => row.method === "DELETE");
    expect.soft(cancelled).toHaveLength(1);
    if (cancelled[0]) {
      expect(cancelled[0].headers.get("X-Agent-Id")).toBe("A");
      expect(
        new URL(cancelled[0].url, "https://console.test").searchParams.get(
          "token",
        ),
      ).toBe("opaque-A");
    }
  });

  it("fetches and polls for captured A while storage currently selects B", async () => {
    const view = renderHook(() => useWechat("A"));
    await act(async () => {
      await view.result.current.fetchQrcode();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    const requests = rows.filter((row) => row.method === "GET");
    expect(requests).toHaveLength(2);
    expect(requests.map((row) => row.headers.get("X-Agent-Id"))).toEqual([
      "A",
      "A",
    ]);
    expect(
      new URL(requests[1].url, "https://console.test").searchParams.get(
        "token",
      ),
    ).toBe("opaque-A");
  });

  it("returns success provenance together with token and base URL", async () => {
    platform = async (url) =>
      json(
        url.includes("/status?") ? { status: "confirmed", credentials } : qr,
      );
    const view = renderHook(() => useWechat("A"));
    await act(async () => {
      await view.result.current.fetchQrcode();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(successes).toEqual([
      [
        credentials,
        { agentId: "A", channel: "wechat", token: "opaque-A" },
        expect.objectContaining({
          take: expect.any(Function),
          cancel: expect.any(Function),
        }),
      ],
    ]);
  });

  it("discards a confirmed in-flight A poll after switching to B", async () => {
    const pending = deferred<Response>();
    platform = async (url) =>
      url.includes("/status?") ? pending.promise : json(qr);
    const view = renderHook(({ agentId }) => useWechat(agentId), {
      initialProps: { agentId: "A" },
    });
    await act(async () => {
      await view.result.current.fetchQrcode();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    view.rerender({ agentId: "B" });
    await act(async () => {
      pending.resolve(json({ status: "confirmed", credentials }));
    });
    expect(successes).toEqual([]);
    expect(view.result.current.qrcodeImg).toBe("");
    expect(errors).toEqual([]);
    const before = rows.filter((row) => row.url.includes("/status?")).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(rows.filter((row) => row.url.includes("/status?"))).toHaveLength(
      before,
    );
  });

  it("does not resurrect an A fetch after reset followed by an ABA switch", async () => {
    const pending = deferred<Response>();
    platform = async () => pending.promise;
    const view = renderHook(({ agentId }) => useWechat(agentId), {
      initialProps: { agentId: "A" },
    });
    let fetching!: Promise<void>;
    act(() => {
      fetching = view.result.current.fetchQrcode();
    });
    act(() => view.result.current.reset());
    view.rerender({ agentId: "B" });
    view.rerender({ agentId: "A" });
    await act(async () => {
      pending.resolve(json(qr));
      await fetching;
    });
    expect(view.result.current.qrcodeImg).toBe("");
    expect(successes).toEqual([]);
    const cancel = rows.filter((row) => row.method === "DELETE");
    expect(cancel).toHaveLength(1);
    expect(cancel[0].headers.get("X-Agent-Id")).toBe("A");
  });

  it("cancels the original A session using DELETE and an encoded token", async () => {
    platform = async () => new Response(null, { status: 204 });
    await channelApi.cancelChannelQrcode("wechat", "opaque A/+", {
      agentId: "A",
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].method).toBe("DELETE");
    expect(rows[0].headers.get("X-Agent-Id")).toBe("A");
    expect(
      new URL(rows[0].url, "https://console.test").searchParams.get("token"),
    ).toBe("opaque A/+");
  });

  it("carries automatic-save provenance through the actual PUT request", async () => {
    const body = {
      enabled: false,
      bot_prefix: "",
      bot_token_file: "",
      ...credentials,
    };
    await channelApi.updateChannelConfig("wechat", body, "A", "opaque-A");
    expect(rows).toHaveLength(1);
    expect(rows[0].method).toBe("PUT");
    expect(rows[0].headers.get("X-Agent-Id")).toBe("A");
    expect(rows[0].headers.get("X-Channel-Auth-Session")).toBe("opaque-A");
  });
});
