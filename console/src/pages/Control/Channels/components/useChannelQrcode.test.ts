import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The api module is mocked once so both QR helpers are stable spies. The hook
// only re-creates fetchQrcode from its config, and the mount effect depends on
// stopPoll alone, so identity churn here cannot retrigger a fetch.
const mocks = vi.hoisted(() => ({
  getChannelQrcode: vi.fn(),
  getChannelQrcodeStatus: vi.fn(),
}));

vi.mock("../../../../api", () => ({
  api: {
    getChannelQrcode: mocks.getChannelQrcode,
    getChannelQrcodeStatus: mocks.getChannelQrcodeStatus,
  },
}));

import { useChannelQrcode, type ChannelQrcodeConfig } from "./useChannelQrcode";

const QR = "data:image/png;base64,QR";

/** Callbacks kept referentially stable across renders (see mock note above). */
const cbs = vi.hoisted(() => ({
  onSuccess: vi.fn(),
  onError: vi.fn(),
}));

const baseConfig = (
  over: Partial<ChannelQrcodeConfig> = {},
): ChannelQrcodeConfig => ({
  channel: "wechat",
  successStatus: "confirmed",
  successCredentialKey: "openid",
  onSuccess: cbs.onSuccess,
  onError: cbs.onError,
  ...over,
});

/** Run the pending fetch and let its awaited api call settle. */
const flush = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};

/** Advance one polling interval and let the status request settle. */
const tick = async (ms = 2000) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe("useChannelQrcode", () => {
  beforeEach(() => {
    cbs.onSuccess.mockReset();
    cbs.onError.mockReset();
    mocks.getChannelQrcode.mockReset();
    mocks.getChannelQrcodeStatus.mockReset();
    mocks.getChannelQrcode.mockResolvedValue({
      qrcode_img: QR,
      poll_token: "tok-1",
    });
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "pending",
      credentials: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ── initial state and fetch ─────────────────────────────────────────────

  it("starts with no image and is not loading until fetchQrcode is called", () => {
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    expect(result.current.qrcodeImg).toBe("");
    expect(result.current.loading).toBe(false);
    expect(mocks.getChannelQrcode).not.toHaveBeenCalled();
  });

  it("stores the returned image and clears the loading flag", async () => {
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    expect(result.current.qrcodeImg).toBe(QR);
    expect(result.current.loading).toBe(false);
    expect(mocks.getChannelQrcode).toHaveBeenCalledWith("wechat", undefined);
  });

  it("forwards the extra query params to the qrcode request", async () => {
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ params: { scene: "login" } })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    expect(mocks.getChannelQrcode).toHaveBeenCalledWith("wechat", {
      scene: "login",
    });
  });

  it("reports a fetch error when the backend returns no image", async () => {
    mocks.getChannelQrcode.mockResolvedValueOnce({
      qrcode_img: "",
      poll_token: "tok-1",
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith("fetch");
    expect(result.current.qrcodeImg).toBe("");
    // The flag must not stay stuck on the early-return path.
    expect(result.current.loading).toBe(false);
  });

  it("reports a fetch error when the qrcode request rejects", async () => {
    mocks.getChannelQrcode.mockRejectedValueOnce(new Error("network down"));
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith("fetch");
    expect(result.current.loading).toBe(false);
  });

  it("does not start polling when there is no image to scan", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcode.mockResolvedValueOnce({
      qrcode_img: "",
      poll_token: "tok-1",
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(6000);

    expect(mocks.getChannelQrcodeStatus).not.toHaveBeenCalled();
  });

  // ── polling: success ────────────────────────────────────────────────────

  it("polls with the token from the fetch response", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();

    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledWith(
      "wechat",
      "tok-1",
      undefined,
    );
  });

  it("honours a custom polling interval", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 500 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    await tick(499);
    expect(mocks.getChannelQrcodeStatus).not.toHaveBeenCalled();

    await tick(1);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);
  });

  it("hands the credentials over and clears the image on success", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "confirmed",
      credentials: { openid: "u-42", token: "t-9" },
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();

    expect(cbs.onSuccess).toHaveBeenCalledWith({
      openid: "u-42",
      token: "t-9",
    });
    expect(cbs.onError).not.toHaveBeenCalled();
    expect(result.current.qrcodeImg).toBe("");
  });

  it("stops polling after a successful confirmation", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "confirmed",
      credentials: { openid: "u-42" },
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);

    await tick(10000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);
  });

  it("does not fire onSuccess again once polling has already stopped", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "confirmed",
      credentials: { openid: "u-42" },
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();
    await tick(4000);

    // Serial polling returns right after a success, so no second tick exists.
    expect(cbs.onSuccess).toHaveBeenCalledTimes(1);
  });

  it("swallows a second confirmation arriving from an overlapping poll", async () => {
    vi.useFakeTimers();

    // Reach the confirmedRef latch, which serial polling cannot: a poll
    // callback must still be awaiting when a re-fetch resets the latch, and
    // the newer poll has to confirm first. Removing the latch lets the stale
    // callback fire onSuccess a second time (verified by mutation).
    let releaseStale: (v: {
      status: string;
      credentials: Record<string, string>;
    }) => void = () => {};
    const stalePending = new Promise<{
      status: string;
      credentials: Record<string, string>;
    }>((resolve) => {
      releaseStale = resolve;
    });

    mocks.getChannelQrcodeStatus
      .mockReturnValueOnce(stalePending)
      .mockResolvedValue({
        status: "confirmed",
        credentials: { openid: "fresh" },
      });

    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 1000 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    // First poll starts and hangs on the unresolved status request.
    await tick(1000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);

    // Re-fetch while that request is in flight: reset() clears the latch and
    // stops the tracked timer, but the running callback is already detached.
    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    // The fresh poll confirms first and latches confirmedRef.
    await tick(1000);
    expect(cbs.onSuccess).toHaveBeenCalledWith({ openid: "fresh" });
    expect(cbs.onSuccess).toHaveBeenCalledTimes(1);

    // Now the stale callback resolves: the latch must swallow it.
    await act(async () => {
      releaseStale({ status: "confirmed", credentials: { openid: "stale" } });
      await stalePending;
    });

    expect(cbs.onSuccess).toHaveBeenCalledTimes(1);
    expect(cbs.onSuccess).not.toHaveBeenCalledWith({ openid: "stale" });
  });

  it("requires the success credential key to be truthy, not just the status", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "confirmed",
      credentials: { openid: "" },
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(6000);

    // Status matches but the credential is empty, so this is not a success and
    // polling keeps going.
    expect(cbs.onSuccess).not.toHaveBeenCalled();
    expect(cbs.onError).not.toHaveBeenCalled();
    expect(result.current.qrcodeImg).toBe(QR);
    expect(mocks.getChannelQrcodeStatus.mock.calls.length).toBeGreaterThan(1);
  });

  it("accepts a different success credential key when configured", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "authorized",
      credentials: { corp_userid: "c-1" },
    });
    const { result } = renderHook(() =>
      useChannelQrcode(
        baseConfig({
          successStatus: "authorized",
          successCredentialKey: "corp_userid",
        }),
      ),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();

    expect(cbs.onSuccess).toHaveBeenCalledWith({ corp_userid: "c-1" });
  });

  // ── polling: terminal failures ──────────────────────────────────────────

  it("reports expiry when the backend says the code expired", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "expired",
      credentials: {},
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();

    expect(cbs.onError).toHaveBeenCalledWith("expired");
    expect(result.current.qrcodeImg).toBe("");
  });

  it("reports failure when the backend rejects the authorization", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "fail",
      credentials: {},
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();

    expect(cbs.onError).toHaveBeenCalledWith("fail");
    expect(result.current.qrcodeImg).toBe("");
  });

  it("stops polling after a terminal backend status", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "expired",
      credentials: {},
    });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);

    await tick(8000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);
  });

  // ── polling: transient errors keep going ────────────────────────────────

  it("keeps polling when a single status request throws", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus
      .mockRejectedValueOnce(new Error("blip"))
      .mockResolvedValue({ status: "pending", credentials: {} });
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();
    await tick();

    // The swallowed error must not surface as a failure nor stop the loop.
    expect(cbs.onError).not.toHaveBeenCalled();
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(2);
    expect(result.current.qrcodeImg).toBe(QR);
  });

  it("keeps polling while the status stays pending", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick();
    await tick();
    await tick();

    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(3);
    expect(cbs.onSuccess).not.toHaveBeenCalled();
    expect(cbs.onError).not.toHaveBeenCalled();
    expect(result.current.qrcodeImg).toBe(QR);
  });

  // ── wall-clock timeout ──────────────────────────────────────────────────

  it("expires on the wall-clock timeout before issuing another request", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 1000, pollTimeout: 2500 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    await tick(1000);
    await tick(1000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(2);

    // At 3000ms the 2500ms budget is spent, so the next tick must short-circuit.
    await tick(1000);

    expect(cbs.onError).toHaveBeenCalledWith("expired");
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(2);
    expect(result.current.qrcodeImg).toBe("");
  });

  it("expires on the attempt-count failsafe", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 1000, maxPollCount: 2 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    await tick(1000);
    await tick(1000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(2);

    await tick(1000);

    expect(cbs.onError).toHaveBeenCalledWith("expired");
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(2);
    expect(result.current.qrcodeImg).toBe("");
  });

  it("polls without a ceiling when neither timeout is configured", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 1000 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(20000);

    expect(cbs.onError).not.toHaveBeenCalled();
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(20);
    expect(result.current.qrcodeImg).toBe(QR);
  });

  it("checks the wall-clock budget before the attempt budget", async () => {
    vi.useFakeTimers();
    // Both limits are already spent at the first tick: the wall-clock branch
    // runs first, so exactly one expiry is reported.
    const { result } = renderHook(() =>
      useChannelQrcode(
        baseConfig({ pollInterval: 1000, pollTimeout: 1, maxPollCount: 0 }),
      ),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(1000);

    expect(cbs.onError).toHaveBeenCalledTimes(1);
    expect(cbs.onError).toHaveBeenCalledWith("expired");
    expect(mocks.getChannelQrcodeStatus).not.toHaveBeenCalled();
  });

  // ── stopPoll and reset ──────────────────────────────────────────────────

  it("stops polling when stopPoll is called", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    act(() => {
      result.current.stopPoll();
    });
    await tick(10000);

    expect(mocks.getChannelQrcodeStatus).not.toHaveBeenCalled();
    // Stopping the poll does not discard an image the user may still scan.
    expect(result.current.qrcodeImg).toBe(QR);
  });

  it("is safe to call stopPoll when nothing is polling", () => {
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    expect(() => {
      act(() => {
        result.current.stopPoll();
        result.current.stopPoll();
      });
    }).not.toThrow();
  });

  it("clears the image and the attempt bookkeeping on reset", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 1000, maxPollCount: 2 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(1000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.reset();
    });
    expect(result.current.qrcodeImg).toBe("");

    // Reset must also stop the in-flight loop.
    await tick(10000);
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledTimes(1);
  });

  it("restarts the attempt budget after a reset, so a second scan can succeed", async () => {
    vi.useFakeTimers();
    mocks.getChannelQrcodeStatus.mockResolvedValue({
      status: "confirmed",
      credentials: { openid: "u-7" },
    });
    const { result } = renderHook(() =>
      useChannelQrcode(baseConfig({ pollInterval: 1000, maxPollCount: 1 })),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(1000);
    expect(cbs.onSuccess).toHaveBeenCalledTimes(1);

    // Without the reset the spent budget would immediately report expiry.
    act(() => {
      result.current.reset();
    });

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    await tick(1000);

    expect(cbs.onError).not.toHaveBeenCalled();
    expect(cbs.onSuccess).toHaveBeenCalledTimes(2);
  });

  it("drops a stale image when a new fetch replaces it", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChannelQrcode(baseConfig()));

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();
    expect(result.current.qrcodeImg).toBe(QR);

    mocks.getChannelQrcode.mockResolvedValueOnce({
      qrcode_img: "data:image/png;base64,SECOND",
      poll_token: "tok-2",
    });

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    expect(result.current.qrcodeImg).toBe("data:image/png;base64,SECOND");
    await tick();
    expect(mocks.getChannelQrcodeStatus).toHaveBeenCalledWith(
      "wechat",
      "tok-2",
      undefined,
    );
  });

  // ── unmount cleanup ─────────────────────────────────────────────────────

  it("clears the pending poll when the component unmounts", async () => {
    vi.useFakeTimers();
    const { result, unmount } = renderHook(() =>
      useChannelQrcode(baseConfig()),
    );

    await act(async () => {
      void result.current.fetchQrcode();
    });
    await flush();

    unmount();
    await tick(10000);

    expect(mocks.getChannelQrcodeStatus).not.toHaveBeenCalled();
  });
});
