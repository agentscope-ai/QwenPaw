/**
 * Session API pure transforms (test-only exports). Regression family:
 * session id resolution (local timestamp ids must never be used as backend
 * UUIDs — 404 loops) and message-to-card conversion (history replay must
 * preserve roles/timestamps/attachments).
 */
import { describe, it, expect, vi } from "vitest";

vi.mock("@agentscope-ai/chat", () => ({}));

import { __test__ as T } from "./index";

type SessionLike = {
  id: string;
  name?: string;
  sessionId?: string;
  realId?: string;
};

const msg = (over: Record<string, unknown> = {}) => ({
  id: "m1",
  role: "user",
  type: "message",
  content: "hello",
  metadata: null,
  ...over,
});

describe("parseTimestamp / parseFinishedAt", () => {
  it("parses a metadata timestamp to unix seconds", () => {
    const m = msg({ metadata: { timestamp: "2026-05-27 10:44:53.362" } });
    const sec = T.parseTimestamp(m as never);
    expect(sec).toBe(
      Math.floor(new Date("2026-05-27T10:44:53.362").getTime() / 1000),
    );
  });

  it("returns 0 for missing metadata", () => {
    expect(T.parseTimestamp(msg() as never)).toBe(0);
    expect(T.parseFinishedAt(msg() as never)).toBe(0);
  });

  it("returns 0 for unparseable strings", () => {
    const m = msg({ metadata: { timestamp: "not a date", finished_at: 42 } });
    expect(T.parseTimestamp(m as never)).toBe(0);
    expect(T.parseFinishedAt(m as never)).toBe(0);
  });

  it("reads finished_at independently of timestamp", () => {
    const m = msg({
      metadata: {
        timestamp: "2026-01-01 00:00:00",
        finished_at: "2026-01-02 00:00:00",
      },
    });
    const ts = T.parseTimestamp(m as never);
    const fa = T.parseFinishedAt(m as never);
    expect(fa).toBeGreaterThan(ts);
  });
});

describe("extractTextFromContent", () => {
  it("returns strings as-is", () => {
    expect(T.extractTextFromContent("plain")).toBe("plain");
  });

  it("joins text items and ignores other types", () => {
    expect(
      T.extractTextFromContent([
        { type: "text", text: "a" },
        { type: "image" },
        { type: "text", text: "b" },
        { type: "text" },
      ]),
    ).toBe("a\nb");
  });

  it("stringifies non-array non-string content", () => {
    expect(T.extractTextFromContent(null)).toBe("");
    expect(T.extractTextFromContent(5)).toBe("5");
  });
});

describe("contentToRequestParts", () => {
  it("wraps plain strings into a text part", () => {
    expect(T.contentToRequestParts("hi")).toEqual([
      { type: "text", text: "hi", status: "created" },
    ]);
  });

  it("returns a single empty text part for empty arrays", () => {
    expect(T.contentToRequestParts([])).toEqual([
      { type: "text", text: "", status: "created" },
    ]);
  });

  it("tags every part with created status", () => {
    const parts = T.contentToRequestParts([{ type: "text", text: "x" }]);
    expect(parts[0].status).toBe("created");
  });
});

describe("toOutputMessage", () => {
  it("maps system plugin_call_output to the tool role", () => {
    const out = T.toOutputMessage(
      msg({ role: "system", type: "plugin_call_output" }) as never,
    );
    expect(out.role).toBe("tool");
  });

  it("keeps other roles untouched and nulls missing metadata", () => {
    const out = T.toOutputMessage(
      msg({ role: "assistant", metadata: undefined }) as never,
    );
    expect(out.role).toBe("assistant");
    expect(out.metadata).toBeNull();
  });
});

describe("buildUserCard", () => {
  it("uses the message id and parses the created timestamp", () => {
    const card = T.buildUserCard(
      msg({
        id: "fixed-id",
        metadata: { timestamp: "2026-01-01 00:00:00" },
      }) as never,
    );
    expect(card.id).toBe("fixed-id");
    expect(card.role).toBe("user");
    expect(card.cards![0].code).toBe("AgentScopeRuntimeRequestCard");
    expect(card.cards![0].data.created_at).toBeGreaterThan(0);
    expect(card.cards![0].data.input[0].content).toEqual([
      { type: "text", text: "hello", status: "created" },
    ]);
  });

  it("generates an id when the message has none", () => {
    const card = T.buildUserCard(msg({ id: "" }) as never);
    expect(card.id).toBeTruthy();
  });
});

describe("isLocalTimestamp", () => {
  it("recognizes local timestamp-random ids", () => {
    expect(T.isLocalTimestamp("1735689600000-abc12")).toBe(true);
  });

  it("rejects backend UUIDs", () => {
    expect(T.isLocalTimestamp("550e8400-e29b-41d4-a716-446655440000")).toBe(
      false,
    );
    expect(T.isLocalTimestamp("")).toBe(false);
  });
});

describe("isGenerating", () => {
  it("is true only for an explicit running status", () => {
    expect(T.isGenerating({ status: "running" } as never)).toBe(true);
  });

  it("treats missing status as idle (no false reconnects)", () => {
    expect(T.isGenerating({} as never)).toBe(false);
    expect(T.isGenerating({ status: "idle" } as never)).toBe(false);
    expect(T.isGenerating({ status: undefined } as never)).toBe(false);
  });
});

describe("resolveRealId", () => {
  const local = (id: string, over: Partial<SessionLike> = {}) =>
    ({
      id,
      name: id,
      sessionId: undefined,
      realId: undefined,
      ...over,
    }) as SessionLike;

  const LOCAL_ID = "1735689600000-abc12"; // local timestamp-random id

  it("returns an already-resolved realId without mutating the list", () => {
    const list = [local(LOCAL_ID, { realId: "uuid-1" })];
    const { list: out, realId } = T.resolveRealId(list as never, LOCAL_ID);
    expect(realId).toBe("uuid-1");
    expect(out).toBe(list);
  });

  it("links a backend chat whose session_id matches the temp id", () => {
    const placeholder = local(LOCAL_ID);
    const backend = { id: "uuid-2", name: "b", sessionId: LOCAL_ID };
    const { list, realId } = T.resolveRealId(
      [placeholder, backend] as never,
      LOCAL_ID,
    );
    expect(realId).toBe("uuid-2");
    // resolved entry moves to the front and adopts the local id
    expect(list[0].id).toBe(LOCAL_ID);
    expect((list[0] as SessionLike).realId).toBe("uuid-2");
  });

  it("never returns a local timestamp id as the real id", () => {
    const placeholder = local(LOCAL_ID);
    const { realId } = T.resolveRealId([placeholder] as never, LOCAL_ID);
    expect(realId).toBeNull();
  });

  it("returns null when nothing matches", () => {
    const { realId } = T.resolveRealId(
      [local("other-uuid")] as never,
      LOCAL_ID,
    );
    expect(realId).toBeNull();
  });

  it("does not use a placeholder sharing the temp id as the backend uuid", () => {
    const placeholder = local(LOCAL_ID);
    const backendSameId = { id: LOCAL_ID, sessionId: LOCAL_ID };
    const { realId } = T.resolveRealId(
      [placeholder, backendSameId] as never,
      LOCAL_ID,
    );
    // branch 2 skips id===tempSessionId; branch 3 finds the placeholder,
    // whose local-timestamp id must never be treated as a backend UUID.
    expect(realId).toBeNull();
  });
});

describe("normalizeOutputMessageContent", () => {
  it("passes strings through", () => {
    expect(T.normalizeOutputMessageContent("x")).toBe("x");
  });

  it("keeps non-array content unchanged", () => {
    expect(T.normalizeOutputMessageContent(42)).toBe(42);
  });
});
