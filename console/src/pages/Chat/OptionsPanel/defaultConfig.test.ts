import { describe, expect, it, vi } from "vitest";
import defaultConfig, {
  configProvider,
  getDefaultConfig,
} from "./defaultConfig";

// A t() that echoes the key makes the substituted values easy to assert.
const t = ((key: string) => key) as unknown as Parameters<
  typeof getDefaultConfig
>[0];

describe("defaultConfig static shape", () => {
  it("carries the brand theme defaults", () => {
    expect(defaultConfig.theme.colorPrimary).toBe("#FF7F16");
    expect(defaultConfig.theme.darkMode).toBe(false);
    expect(defaultConfig.theme.prefix).toBe("qwenpaw");
    expect(defaultConfig.theme.leftHeader).toEqual({
      logo: "",
      title: "Work with QwenPaw",
    });
    expect(defaultConfig.theme.bubbleList.userMessageAnchors.variant).toBe(
      "navigator",
    );
  });

  it("carries the sender defaults including the long-text upload flag", () => {
    expect(defaultConfig.sender.attachments).toBe(true);
    expect(defaultConfig.sender.maxLength).toBe(10000);
    expect(defaultConfig.sender.longTextUpload.enabled).toBe(true);
    expect(defaultConfig.sender.disclaimer).toBe(
      "Works for you, grows with you",
    );
  });

  it("carries the welcome defaults with two prompts and an api stub", () => {
    expect(defaultConfig.welcome.avatar).toBe("/online.svg");
    expect(defaultConfig.welcome.prompts).toHaveLength(2);
    expect(defaultConfig.api).toEqual({ baseURL: "", token: "" });
  });
});

describe("configProvider i18n accessors", () => {
  it("maps the greeting and description to their i18n keys", () => {
    expect(configProvider.getGreeting(t)).toBe("chat.greeting");
    expect(configProvider.getDescription(t)).toBe("chat.description");
  });

  it("builds two prompts from the i18n keys", () => {
    expect(configProvider.getPrompts(t)).toEqual([
      { value: "chat.prompt1" },
      { value: "chat.prompt2" },
    ]);
  });
});

describe("getDefaultConfig", () => {
  it("overrides the translatable welcome/sender fields while keeping the rest", () => {
    const cfg = getDefaultConfig(t);
    expect(cfg.sender.disclaimer).toBe("chat.disclaimer");
    expect(cfg.welcome.greeting).toBe("chat.greeting");
    expect(cfg.welcome.description).toBe("chat.description");
    expect(cfg.welcome.prompts).toEqual([
      { value: "chat.prompt1" },
      { value: "chat.prompt2" },
    ]);
    // Untouched defaults survive the spread.
    expect(cfg.sender.maxLength).toBe(10000);
    expect(cfg.theme.colorPrimary).toBe("#FF7F16");
    expect(cfg.welcome.avatar).toBe("/online.svg");
    expect(cfg.api).toEqual({ baseURL: "", token: "" });
  });

  it("does not mutate the shared defaultConfig object", () => {
    getDefaultConfig(t);
    expect(defaultConfig.sender.disclaimer).toBe(
      "Works for you, grows with you",
    );
    expect(defaultConfig.welcome.greeting).toBe(
      "Hello, how can I help you today?",
    );
  });

  it("reflects whatever the translate function returns", () => {
    const zh = vi.fn((key: string) => `ZH:${key}`) as unknown as typeof t;
    const cfg = getDefaultConfig(zh);
    expect(cfg.welcome.greeting).toBe("ZH:chat.greeting");
    expect(cfg.sender.disclaimer).toBe("ZH:chat.disclaimer");
    expect(zh).toHaveBeenCalledWith("chat.greeting");
  });
});
