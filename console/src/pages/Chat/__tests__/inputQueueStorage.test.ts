import { beforeEach, describe, expect, it } from "vitest";
import {
  hasStoredInputQueueItems,
  removeStoredInputQueueItem,
} from "../inputQueueStorage";

const queueSessionId = "agent-1::chat-1";
const storageKey = "agentscope-runtime-webui-input-queue:agent-1::chat-1";

describe("input queue accepted-request recovery", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("removes only the accepted request restored at the queue head", () => {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        items: [
          {
            id: "accepted",
            data: { query: "same", qwenpaw_queue_request_id: "request-1" },
          },
          {
            id: "next",
            data: { query: "same", qwenpaw_queue_request_id: "request-2" },
          },
        ],
        paused: false,
        ownerTabId: "tab-1",
        updatedAt: 1,
      }),
    );

    expect(hasStoredInputQueueItems(queueSessionId)).toBe(true);
    expect(removeStoredInputQueueItem(queueSessionId, "request-1")).toBe(true);
    expect(JSON.parse(localStorage.getItem(storageKey) || "{}").items).toEqual([
      {
        id: "next",
        data: { query: "same", qwenpaw_queue_request_id: "request-2" },
      },
    ]);
  });

  it("preserves the queue when the accepted request ID is absent", () => {
    const value = JSON.stringify({
      items: [
        {
          id: "next",
          data: { query: "same", qwenpaw_queue_request_id: "request-2" },
        },
      ],
      paused: false,
      updatedAt: 1,
    });
    localStorage.setItem(storageKey, value);

    expect(removeStoredInputQueueItem(queueSessionId, "request-1")).toBe(false);
    expect(localStorage.getItem(storageKey)).toBe(value);
  });

  it("removes an accepted request whose id is transported in biz_params", () => {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        items: [
          {
            id: "accepted",
            data: {
              query: "queued",
              biz_params: { __qwenpaw_queue_request_id: "request-biz" },
            },
          },
        ],
        paused: false,
        updatedAt: 1,
      }),
    );

    expect(removeStoredInputQueueItem(queueSessionId, "request-biz")).toBe(
      true,
    );
    expect(localStorage.getItem(storageKey)).toBeNull();
  });
});
