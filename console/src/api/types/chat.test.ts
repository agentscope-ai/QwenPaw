import { describe, expect, it } from "vitest";

import { isRealtimeVoiceChat, type ChatSpec } from "./chat";

describe("isRealtimeVoiceChat", () => {
  it("identifies voice capability without a new persisted source value", () => {
    const chat: Pick<ChatSpec, "meta"> = {
      meta: { realtime_voice: { version: 3 } },
    };

    expect(isRealtimeVoiceChat(chat)).toBe(true);
  });

  it("does not classify an ordinary chat as voice", () => {
    expect(isRealtimeVoiceChat({} as ChatSpec)).toBe(false);
  });
});
