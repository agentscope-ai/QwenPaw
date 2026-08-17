/**
 * getBackendSessionIdStrict / isKnownBackendSessionId must never hand back
 * an id the backend cannot confirm. The lenient getBackendSessionId falls
 * back to the raw input, which let stale chat UUIDs and unresolved local
 * timestamp ids leak into tool-call APIs that validate the session_id
 * (404 "session_id mismatch" storms).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/modules/chat", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../../api/modules/chat")
  >();
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      filePreviewUrl: vi.fn((p: string) => p),
    },
  };
});

// Import AFTER mocks are registered.
import sessionApi from "../sessionApi";

interface SessionApiTestAccess {
  sessionList: Array<Record<string, unknown>>;
}

const testApi = sessionApi as unknown as SessionApiTestAccess;

function setSessions(
  rows: Array<{ id: string; sessionId: string; realId?: string | null }>,
): void {
  testApi.sessionList = rows.map((r) => ({ ...r }));
}

beforeEach(() => {
  setSessions([]);
});

describe("getBackendSessionIdStrict", () => {
  it("resolves a library id (session.id) to the backend sessionId", () => {
    setSessions([
      { id: "uuid-1", sessionId: "console:default", realId: "uuid-1" },
    ]);
    expect(sessionApi.getBackendSessionIdStrict("uuid-1")).toBe(
      "console:default",
    );
  });

  it("resolves via realId", () => {
    setSessions([
      { id: "uuid-1", sessionId: "console:default", realId: "uuid-1" },
    ]);
    expect(sessionApi.getBackendSessionIdStrict("uuid-1")).toBe(
      "console:default",
    );
    // A resolved local session keeps its ts id as `id` and the UUID as realId.
    setSessions([
      {
        id: "1782267071416-qs7yghe",
        sessionId: "console:default",
        realId: "uuid-2",
      },
    ]);
    expect(
      sessionApi.getBackendSessionIdStrict("1782267071416-qs7yghe"),
    ).toBe("console:default");
    expect(sessionApi.getBackendSessionIdStrict("uuid-2")).toBe(
      "console:default",
    );
  });

  it("returns the input unchanged when it already is a known backend sessionId", () => {
    setSessions([
      { id: "uuid-1", sessionId: "console:default", realId: "uuid-1" },
    ]);
    expect(sessionApi.getBackendSessionIdStrict("console:default")).toBe(
      "console:default",
    );
  });

  it('returns "" for an unknown id (stale chat UUID not in the list)', () => {
    setSessions([
      { id: "uuid-1", sessionId: "console:default", realId: "uuid-1" },
    ]);
    expect(
      sessionApi.getBackendSessionIdStrict(
        "2cbdb459-91ff-4a02-acd3-efd7df52ddad",
      ),
    ).toBe("");
  });

  it('returns "" for an unresolved local timestamp session', () => {
    // createEmptySession puts the local ts id into both id and sessionId;
    // nothing about it is backend-known yet.
    setSessions([
      { id: "1782267071416-qs7yghe", sessionId: "1782267071416-qs7yghe" },
    ]);
    expect(
      sessionApi.getBackendSessionIdStrict("1782267071416-qs7yghe"),
    ).toBe("");
  });

  it('returns "" for empty input', () => {
    expect(sessionApi.getBackendSessionIdStrict("")).toBe("");
  });
});

describe("isKnownBackendSessionId", () => {
  it("matches the sessionId of a resolved session", () => {
    setSessions([
      { id: "uuid-1", sessionId: "console:default", realId: "uuid-1" },
    ]);
    expect(sessionApi.isKnownBackendSessionId("console:default")).toBe(true);
    expect(sessionApi.isKnownBackendSessionId("console:other")).toBe(false);
  });

  it("does not match the placeholder sessionId of an unresolved local session", () => {
    setSessions([
      { id: "1782267071416-qs7yghe", sessionId: "1782267071416-qs7yghe" },
    ]);
    expect(
      sessionApi.isKnownBackendSessionId("1782267071416-qs7yghe"),
    ).toBe(false);
  });

  it("returns false for empty input", () => {
    expect(sessionApi.isKnownBackendSessionId("")).toBe(false);
  });
});

describe("lenient getBackendSessionId is unchanged", () => {
  it("still falls back to the input id (used only on non-validating paths)", () => {
    expect(sessionApi.getBackendSessionId("anything")).toBe("anything");
  });
});
