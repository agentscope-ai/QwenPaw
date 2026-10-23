import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { channelApi } from "../api/modules/channel";
import type { WeChatConfig } from "../api/types";
import { useAutoSave } from "./useAutoSave";

const feedback = vi.hoisted(() => ({ error: vi.fn(), destroy: vi.fn() }));
vi.mock("./useAppMessage", () => ({
  useAppMessage: () => ({ message: feedback }),
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

type SaveRow = { headers: Headers; body: unknown };
const writes: SaveRow[] = [];
const bodyA: WeChatConfig = {
  enabled: false,
  bot_prefix: "",
  bot_token: "candidate-A",
  bot_token_file: "",
  base_url: "https://wx.test",
};

function saveA() {
  return channelApi
    .updateChannelConfig("wechat", bodyA, "A", "opaque-A")
    .then(() => undefined);
}

function useSettings(agentId: string) {
  return useAutoSave(() =>
    channelApi
      .updateChannelConfig(
        "wechat",
        { ...bodyA, bot_token: "manual-" + agentId },
        agentId,
      )
      .then(() => undefined),
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  writes.length = 0;
  feedback.error.mockReset();
  feedback.destroy.mockReset();
  vi.stubGlobal("fetch", async (_url: string, init: RequestInit = {}) => {
    writes.push({
      headers: new Headers(init.headers),
      body: JSON.parse(String(init.body)),
    });
    return new Response(JSON.stringify(bodyA), {
      headers: { "Content-Type": "application/json" },
    });
  });
});

afterEach(async () => {
  cleanup();
  await act(async () => {});
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function expectOnlyCapturedA() {
  expect(writes).toHaveLength(1);
  expect(writes[0].headers.get("X-Agent-Id")).toBe("A");
  expect(writes[0].headers.get("X-Channel-Auth-Session")).toBe("opaque-A");
  expect(writes[0].body).toEqual(bodyA);
}

describe("WeChat fixed save jobs through useAutoSave and the real PUT serializer", () => {
  it("does not replace a queued A authorization job with latest.current for B", async () => {
    const view = renderHook(({ agentId }) => useSettings(agentId), {
      initialProps: { agentId: "A" },
    });
    act(() => view.result.current.schedule(saveA));
    view.rerender({ agentId: "B" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expectOnlyCapturedA();
  });

  it("unmount flushes the captured authorization job with its provenance", async () => {
    const view = renderHook(() => useSettings("B"));
    act(() => view.result.current.schedule(saveA));
    view.unmount();
    await act(async () => {});
    expectOnlyCapturedA();
  });

  it("leaves ordinary no-job manual autosave on its existing path", async () => {
    const view = renderHook(() => useSettings("B"));
    act(() => view.result.current.schedule());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(writes).toHaveLength(1);
    expect(writes[0].headers.get("X-Agent-Id")).toBe("B");
    expect(writes[0].headers.has("X-Channel-Auth-Session")).toBe(false);
    expect(writes[0].body).toEqual({
      enabled: false,
      bot_prefix: "",
      bot_token: "manual-B",
      bot_token_file: "",
      base_url: "https://wx.test",
    });
  });
});
