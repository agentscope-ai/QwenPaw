/**
 * Tests for constants/channel.
 *
 * Covers:
 * - CHANNELS object keys and values
 * - CHANNEL_COLORS keys match CHANNELS
 * - CHANNEL_COLORS values are valid color names
 */
import { describe, it, expect } from "vitest";
import { CHANNELS, CHANNEL_COLORS } from "./channel";

describe("CHANNELS", () => {
  it("is a non-empty object", () => {
    expect(Object.keys(CHANNELS).length).toBeGreaterThan(0);
  });

  it("each key maps to a matching string value", () => {
    for (const [key, value] of Object.entries(CHANNELS)) {
      expect(value).toBe(key);
    }
  });

  it("contains expected channel types", () => {
    expect(CHANNELS.discord).toBe("discord");
    expect(CHANNELS.dingtalk).toBe("dingtalk");
    expect(CHANNELS.feishu).toBe("feishu");
    expect(CHANNELS.telegram).toBe("telegram");
    expect(CHANNELS.console).toBe("console");
  });
});

describe("CHANNEL_COLORS", () => {
  it("has a color entry for every channel", () => {
    for (const key of Object.keys(CHANNELS)) {
      expect(CHANNEL_COLORS).toHaveProperty(key);
    }
  });

  it("color values are non-empty strings", () => {
    for (const value of Object.values(CHANNEL_COLORS)) {
      expect(typeof value).toBe("string");
      expect(value.length).toBeGreaterThan(0);
    }
  });
});
