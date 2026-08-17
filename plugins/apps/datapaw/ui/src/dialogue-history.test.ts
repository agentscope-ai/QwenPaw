import { describe, expect, it } from "vitest";

import { nextActiveSessionId, sortChatSessions } from "./ChatWorkspace";
import type { PawChatSession } from "./sdk";

function session(
  id: string,
  updatedAt: string,
  pinned = false,
): PawChatSession {
  return {
    id,
    sessionId: `pawapp:datapaw:dialogue:${id}`,
    name: id,
    createdAt: updatedAt,
    updatedAt,
    archived: false,
    pinned,
  };
}

describe("DataPaw dialogue history", () => {
  it("orders pinned dialogues first, then most recently updated", () => {
    const ordered = sortChatSessions([
      session("stale", "2026-08-01T00:00:00Z"),
      session("fresh", "2026-08-11T00:00:00Z"),
      session("pinned-old", "2026-07-01T00:00:00Z", true),
    ]);

    expect(ordered.map((item) => item.id)).toEqual([
      "pinned-old",
      "fresh",
      "stale",
    ]);
  });

  it("keeps the active dialogue when another one is removed", () => {
    const sessions = [
      session("a", "2026-08-11T00:00:00Z"),
      session("b", "2026-08-10T00:00:00Z"),
    ];

    expect(
      nextActiveSessionId(
        sessions,
        sessions[1].sessionId,
        sessions[0].sessionId,
      ),
    ).toBe(sessions[0].sessionId);
  });

  it("promotes the next best dialogue when the active one is removed", () => {
    const sessions = [
      session("a", "2026-08-11T00:00:00Z"),
      session("pinned", "2026-08-01T00:00:00Z", true),
    ];

    expect(
      nextActiveSessionId(
        sessions,
        sessions[0].sessionId,
        sessions[0].sessionId,
      ),
    ).toBe(sessions[1].sessionId);
  });

  it("returns no session when the last dialogue is removed", () => {
    const sessions = [session("only", "2026-08-11T00:00:00Z")];

    expect(
      nextActiveSessionId(
        sessions,
        sessions[0].sessionId,
        sessions[0].sessionId,
      ),
    ).toBe("");
  });
});
