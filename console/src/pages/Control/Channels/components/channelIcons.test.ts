import { describe, it, expect } from "vitest";
import {
  getChannelIconUrl,
  getChannelLetterColor,
  CHANNEL_DEFAULT_ICON_URL,
} from "./channelIcons";

describe("getChannelIconUrl", () => {
  it("returns specific CDN URL for known channel 'dingtalk'", () => {
    const url = getChannelIconUrl("dingtalk");
    expect(url).toMatch(/^https:\/\/gw\.alicdn\.com/);
    expect(url).toBe(
      "https://gw.alicdn.com/imgextra/i4/O1CN01g1u9vB1KdEreWzDdv_!!6000000001186-2-tps-400-400.png",
    );
  });

  it("returns specific CDN URL for known channel 'discord'", () => {
    const url = getChannelIconUrl("discord");
    expect(url).toBe(
      "https://gw.alicdn.com/imgextra/i4/O1CN01BQFnBu21PWTtKbPmU_!!6000000006977-2-tps-400-400.png",
    );
  });

  it("returns CHANNEL_DEFAULT_ICON_URL for unknown channel", () => {
    const url = getChannelIconUrl("unknown_channel");
    expect(url).toBe(CHANNEL_DEFAULT_ICON_URL);
  });

  it("CHANNEL_DEFAULT_ICON_URL is a non-empty string starting with 'https://'", () => {
    expect(CHANNEL_DEFAULT_ICON_URL).toBeTruthy();
    expect(typeof CHANNEL_DEFAULT_ICON_URL).toBe("string");
    expect(CHANNEL_DEFAULT_ICON_URL).toMatch(/^https:\/\//);
  });
});

describe("getChannelLetterColor", () => {
  it("returns predefined color '#FF7F16' for known channel 'console'", () => {
    expect(getChannelLetterColor("console")).toBe("#FF7F16");
  });

  it("returns predefined color '#5865F2' for known channel 'discord'", () => {
    expect(getChannelLetterColor("discord")).toBe("#5865F2");
  });

  it("returns a color string starting with '#' for unknown channel 'my_custom_bot'", () => {
    const color = getChannelLetterColor("my_custom_bot");
    expect(typeof color).toBe("string");
    expect(color).toMatch(/^#/);
  });

  it("returns the same color on repeated calls for the same unknown channel (deterministic hash)", () => {
    const color1 = getChannelLetterColor("my_custom_bot");
    const color2 = getChannelLetterColor("my_custom_bot");
    expect(color1).toBe(color2);
  });
});
