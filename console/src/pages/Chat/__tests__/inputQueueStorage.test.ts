import { beforeEach, describe, expect, it } from "vitest";
import {
  clearLegacyStoredMessageQueue,
  clearStoredInputQueue,
  hasStoredInputQueueItems,
} from "../inputQueueStorage";

const queueSessionId = "agent-1::chat-1";
const storageKey = "agentscope-runtime-webui-input-queue:agent-1::chat-1";

describe("input queue storage cleanup", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("clears all SDK queue state when a session is removed", () => {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        items: [{ id: "queued", data: { query: "later" } }],
        paused: true,
        ownerTabId: "tab-1",
      }),
    );

    expect(hasStoredInputQueueItems(queueSessionId)).toBe(true);
    clearStoredInputQueue(queueSessionId);

    expect(localStorage.getItem(storageKey)).toBeNull();
  });

  it("cleans legacy queue storage without loading the removed store", () => {
    const legacyKey = "qwenpaw:message-queue:chat-1";
    localStorage.setItem(legacyKey, "local");
    sessionStorage.setItem(legacyKey, "session");

    clearLegacyStoredMessageQueue("chat-1");

    expect(localStorage.getItem(legacyKey)).toBeNull();
    expect(sessionStorage.getItem(legacyKey)).toBeNull();
  });
});
