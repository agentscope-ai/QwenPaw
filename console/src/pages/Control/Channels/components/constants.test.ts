import { describe, it, expect, vi } from "vitest";
import { CHANNEL_LABELS, getChannelLabel } from "./constants";

describe("CHANNEL_LABELS", () => {
  it("contains known channels: discord, dingtalk, console", () => {
    expect(CHANNEL_LABELS["discord"]).toBe("Discord");
    expect(CHANNEL_LABELS["dingtalk"]).toBe("DingTalk");
    expect(CHANNEL_LABELS["console"]).toBe("Console");
  });
});

describe("getChannelLabel", () => {
  it("returns the English label for a known channel without t", () => {
    expect(getChannelLabel("discord")).toBe("Discord");
  });

  it("formats snake_case custom channel key to Title Case", () => {
    expect(getChannelLabel("custom_channel")).toBe("Custom Channel");
  });

  it("formats kebab-case custom channel key to Title Case", () => {
    expect(getChannelLabel("my-bot")).toBe("My Bot");
  });

  it("calls t with the correct key and defaultValue when t is provided", () => {
    const t = vi.fn(
      (key: string, opts?: { defaultValue?: string }) =>
        opts?.defaultValue ?? key,
    );
    getChannelLabel("discord", t as any);
    expect(t).toHaveBeenCalledWith("channels.channelNames.discord", {
      defaultValue: "Discord",
    });
  });
});
