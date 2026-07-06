/**
 * Tests for api/modules/channel.ts
 *
 * Contract-guard style.  `channelApi` has several non-trivial transforms:
 *  - URL-encoding channel names that contain special characters
 *  - building an optional query-string for QR-code params
 *  - building a query-string for QR-code status with token + extra params
 * We verify these transforms without pinning the exact path string, per #5438.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { channelApi } from "./channel";
import { request } from "../request";

describe("channelApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // ---- listing & shape ---------------------------------------------------

  it("listChannelTypes resolves to a string[] of channel type names", async () => {
    vi.mocked(request).mockResolvedValue(["dingtalk", "wechat"]);
    await expect(channelApi.listChannelTypes()).resolves.toEqual([
      "dingtalk",
      "wechat",
    ]);
  });

  it("listChannels resolves to the ChannelConfig object", async () => {
    const cfg = { dingtalk: { enabled: true } } as unknown;
    vi.mocked(request).mockResolvedValue(cfg);
    expect(await channelApi.listChannels()).toBe(cfg);
  });

  it("updateChannels returns the persisted ChannelConfig", async () => {
    const cfg = { dingtalk: { enabled: false } } as unknown;
    vi.mocked(request).mockResolvedValue(cfg);
    const result = await channelApi.updateChannels(cfg as never);
    expect(result).toBe(cfg);
  });

  // ---- single-channel config --------------------------------------------

  it("getChannelConfig returns a SingleChannelConfig", async () => {
    const single = { enabled: true, webhooks: [] } as unknown;
    vi.mocked(request).mockResolvedValue(single);
    const r = await channelApi.getChannelConfig("dingtalk");
    expect(r).toBe(single);
  });

  it("updateChannelConfig returns the persisted SingleChannelConfig", async () => {
    const single = { enabled: false, webhooks: [] } as unknown;
    vi.mocked(request).mockResolvedValue(single);
    const r = await channelApi.updateChannelConfig("dingtalk", single as never);
    expect(r).toBe(single);
  });

  // ---- URL-encoding of channel names ------------------------------------

  it("encodes a channel name with a slash when calling getChannelConfig", async () => {
    vi.mocked(request).mockResolvedValue({});
    await channelApi.getChannelConfig("a/b");
    const arg = vi.mocked(request).mock.calls[0][0] as string;
    // slash must be percent-encoded so it isn't treated as a path segment
    expect(arg).toContain("a%2Fb");
    expect(arg).not.toMatch(/\/a\/b\b/);
  });

  // ---- QR-code helpers ---------------------------------------------------

  it("getChannelQrcode returns { qrcode_img, poll_token }", async () => {
    const resp = { qrcode_img: "data:...", poll_token: "tok-1" };
    vi.mocked(request).mockResolvedValue(resp);
    await expect(channelApi.getChannelQrcode("wechat")).resolves.toEqual(resp);
  });

  it("getChannelQrcode forwards optional params (e.g. scene) without dropping them", async () => {
    vi.mocked(request).mockResolvedValue({ qrcode_img: "", poll_token: "t" });
    await channelApi.getChannelQrcode("wechat", { scene: "login" });
    const arg = vi.mocked(request).mock.calls[0][0] as string;
    expect(arg).toContain("scene=login");
  });

  it("getChannelQrcodeStatus returns { status, credentials }", async () => {
    const resp = { status: "confirmed", credentials: { openid: "u1" } };
    vi.mocked(request).mockResolvedValue(resp);
    await expect(
      channelApi.getChannelQrcodeStatus("wechat", "tok-1"),
    ).resolves.toEqual(resp);
  });

  it("getChannelQrcodeStatus includes the encoded token in the path it sends to request", async () => {
    vi.mocked(request).mockResolvedValue({
      status: "pending",
      credentials: {},
    });
    await channelApi.getChannelQrcodeStatus("wechat", "tok with space");
    const arg = vi.mocked(request).mock.calls[0][0] as string;
    // token must appear percent-encoded, not raw with spaces
    expect(arg).toContain("tok%20with%20space");
  });

  // ---- error propagation -------------------------------------------------

  it("propagates request errors for listChannels", async () => {
    vi.mocked(request).mockRejectedValue(new Error("503"));
    await expect(channelApi.listChannels()).rejects.toThrow("503");
  });
});
