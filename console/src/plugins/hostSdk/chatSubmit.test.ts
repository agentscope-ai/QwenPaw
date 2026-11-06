import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bindChatSubmit, submitChat } from "./chatSubmit";
import i18n, { i18nReady } from "../../i18n";

let previousLanguage: string;
beforeEach(async () => {
  await i18nReady;
  previousLanguage = i18n.language;
  await i18n.changeLanguage("en");
});
afterEach(async () => {
  await i18n.changeLanguage(previousLanguage);
});

describe("plugin chat submission bridge", () => {
  const input = { query: " use 8 seeds ", agentId: "a", sessionId: "s" };
  it("uses the current language when chat is unavailable", async () => {
    await i18n.changeLanguage("zh");
    await expect(submitChat("p", input)).rejects.toThrow(
      "对话尚未就绪，请打开原来的对话后重试。",
    );
    await i18n.changeLanguage("en");
    await expect(submitChat("p", input)).rejects.toThrow("Chat is not ready.");
  });
  it("rejects unavailable chat and invalid actions", async () => {
    await expect(submitChat("p", input)).rejects.toThrow("not ready");
    await expect(submitChat("p", { ...input, query: " " })).rejects.toThrow(
      "required",
    );
  });
  it("forwards a captured scope once, propagates admission errors and safely cleans up", async () => {
    const oldHandler = vi.fn();
    const old = bindChatSubmit(oldHandler);
    const handler = vi.fn();
    const active = bindChatSubmit(handler);
    old.dispose();
    await submitChat("p", input);
    expect(handler).toHaveBeenCalledExactlyOnceWith({
      ...input,
      query: "use 8 seeds",
    });
    expect(oldHandler).not.toHaveBeenCalled();
    handler.mockRejectedValueOnce(new Error("wrong session"));
    await expect(submitChat("p", input)).rejects.toThrow("wrong session");
    active.dispose();
    await expect(submitChat("p", input)).rejects.toThrow("not ready");
  });
});
