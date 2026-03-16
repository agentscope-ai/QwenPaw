/**
 * Bug Condition Exploration Test
 *
 * Property 1: Bug Condition - updateSession 清空已有消息
 *
 * **Validates: Requirements 1.1, 1.2, 2.1, 2.2**
 *
 * Bug condition: when sessionList contains a session with id === session.id
 * and that session has messages.length > 0, calling updateSession should
 * preserve the messages. The bug is that updateSession sets session.messages = []
 * on line 444, which overwrites existing messages via the spread operator.
 *
 * This test is EXPECTED TO FAIL on unfixed code, confirming the bug exists.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import fc from "fast-check";

// Mock the api module to prevent real HTTP calls
vi.mock("../../../api", () => ({
  default: {
    listChats: vi.fn().mockResolvedValue([]),
    getChat: vi.fn().mockResolvedValue({ messages: [] }),
    deleteChat: vi.fn().mockResolvedValue(undefined),
  },
  api: {
    listChats: vi.fn().mockResolvedValue([]),
    getChat: vi.fn().mockResolvedValue({ messages: [] }),
    deleteChat: vi.fn().mockResolvedValue(undefined),
  },
}));

// Mock window globals used by SessionApi
vi.stubGlobal("window", {
  currentSessionId: undefined,
  currentUserId: undefined,
  currentChannel: undefined,
});

import sessionApi from "./index";

/**
 * Helper: access the private sessionList via type assertion.
 * This is necessary because SessionApi only exports a singleton instance
 * and sessionList is private.
 */
function getSessionList(
  api: typeof sessionApi,
): Array<{
  id: string;
  name: string;
  messages: unknown[];
  [k: string]: unknown;
}> {
  return (
    api as unknown as {
      sessionList: Array<{
        id: string;
        name: string;
        messages: unknown[];
        [k: string]: unknown;
      }>;
    }
  ).sessionList;
}

function setSessionList(
  api: typeof sessionApi,
  list: Array<{
    id: string;
    name: string;
    messages: unknown[];
    [k: string]: unknown;
  }>,
): void {
  (api as unknown as { sessionList: typeof list }).sessionList = list;
}

/**
 * Arbitrary: generate a non-empty array of fake messages.
 * Messages have { id, role, cards } matching IAgentScopeRuntimeWebUIMessage.
 */
const arbMessage = fc.record({
  id: fc.string({ minLength: 1, maxLength: 20 }),
  role: fc.constantFrom(
    "user" as const,
    "assistant" as const,
    "system" as const,
  ),
  cards: fc.constant([]),
});

const arbNonEmptyMessages = fc.array(arbMessage, {
  minLength: 1,
  maxLength: 10,
});

/**
 * Arbitrary: generate a session id that is NOT a local timestamp
 * (i.e., contains non-digit characters) to avoid triggering the
 * realId resolution path which calls getSessionList.
 */
const arbUUIDSessionId = fc.uuid();

describe("Bug Condition Exploration: updateSession clears existing messages", () => {
  beforeEach(() => {
    // Reset sessionList to empty before each test
    setSessionList(sessionApi, []);
  });

  it("Property 1: updateSession should preserve messages when updating metadata only", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUUIDSessionId,
        fc.string({ minLength: 1, maxLength: 50 }),
        arbNonEmptyMessages,
        fc.string({ minLength: 1, maxLength: 50 }),
        async (sessionId, originalName, messages, newName) => {
          // Pre-condition: newName differs from originalName
          fc.pre(newName !== originalName);

          // Setup: place a session with non-empty messages in sessionList
          setSessionList(sessionApi, [
            {
              id: sessionId,
              name: originalName,
              messages: [...messages],
              meta: {},
              sessionId: sessionId,
              userId: "default",
              channel: "console",
            },
          ]);

          // Capture messages before the call
          const messagesBefore = [...getSessionList(sessionApi)[0].messages];

          // Act: call updateSession with only metadata update (no messages field)
          await sessionApi.updateSession({ id: sessionId, name: newName });

          // Assert: messages in sessionList should be preserved
          const sessionAfter = getSessionList(sessionApi).find(
            (s) => s.id === sessionId,
          );
          expect(sessionAfter).toBeDefined();
          expect(sessionAfter!.messages).toEqual(messagesBefore);
          expect(sessionAfter!.messages.length).toBeGreaterThan(0);
        },
      ),
      { numRuns: 100 },
    );
  });
});

/**
 * Preservation Property Tests
 *
 * Property 2: Preservation - 元数据更新和 realId 解析行为不变
 *
 * **Validates: Requirements 3.1, 3.2, 3.4, 3.5**
 *
 * These tests verify behaviors that must remain unchanged after the bugfix.
 * They run on UNFIXED code and are EXPECTED TO PASS, establishing a baseline.
 *
 * Preservation scope: for all inputs where the bug condition does NOT hold
 * (session not in sessionList, or session has empty messages), the behavior
 * of updateSession should be identical before and after the fix.
 */

import api from "../../../api";

describe("Preservation: updateSession metadata update and realId resolution", () => {
  beforeEach(() => {
    setSessionList(sessionApi, []);
    // Reset onSessionIdResolved callback
    sessionApi.onSessionIdResolved = null;
    // Clear mock call history
    vi.clearAllMocks();
  });

  /**
   * Observation 1: On unfixed code, updateSession({ id, name: "新名称" })
   * correctly updates the `name` field in sessionList.
   *
   * Test: For sessions with empty messages (not bug condition),
   * metadata fields are correctly merged into sessionList.
   */
  it("Preservation: metadata update correctly merges name for sessions with empty messages", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUUIDSessionId,
        fc.string({ minLength: 1, maxLength: 50 }),
        fc.string({ minLength: 1, maxLength: 50 }),
        async (sessionId, originalName, newName) => {
          // Pre-condition: names differ
          fc.pre(newName !== originalName);

          // Setup: session with EMPTY messages (not bug condition)
          setSessionList(sessionApi, [
            {
              id: sessionId,
              name: originalName,
              messages: [],
              meta: {},
              sessionId: sessionId,
              userId: "default",
              channel: "console",
            },
          ]);

          // Act
          await sessionApi.updateSession({ id: sessionId, name: newName });

          // Assert: name is updated
          const sessionAfter = getSessionList(sessionApi).find(
            (s) => s.id === sessionId,
          );
          expect(sessionAfter).toBeDefined();
          expect(sessionAfter!.name).toBe(newName);
          // messages remain empty (were already empty)
          expect(sessionAfter!.messages).toEqual([]);
        },
      ),
      { numRuns: 100 },
    );
  });

  /**
   * Observation 2: On unfixed code, for isLocalTimestamp(id) sessions
   * without realId, updateSession triggers getSessionList + resolveRealId.
   *
   * Test: When session id is a pure-digit timestamp and has no realId,
   * updateSession triggers the resolution flow (calls listChats).
   */
  it("Preservation: realId resolution is triggered for local timestamp sessions without realId", async () => {
    // Arbitrary: generate a pure-digit timestamp id (isLocalTimestamp returns true)
    const arbTimestampId = fc.stringMatching(/^\d{5,15}$/);

    await fc.assert(
      fc.asyncProperty(
        arbTimestampId,
        fc.string({ minLength: 1, maxLength: 50 }),
        async (timestampId, sessionName) => {
          // Setup: session with timestamp id, empty messages, no realId
          setSessionList(sessionApi, [
            {
              id: timestampId,
              name: sessionName,
              messages: [],
              meta: {},
              sessionId: timestampId,
              userId: "default",
              channel: "console",
            },
          ]);

          // Track onSessionIdResolved calls
          const resolvedCalls: Array<{ tempId: string; realId: string }> = [];
          sessionApi.onSessionIdResolved = (tempId, realId) => {
            resolvedCalls.push({ tempId, realId });
          };

          // Clear mock to track new calls
          vi.mocked(api.listChats).mockClear();
          vi.mocked(api.listChats).mockResolvedValue([]);

          // Act
          await sessionApi.updateSession({
            id: timestampId,
            name: sessionName,
          });

          // Allow microtasks to flush (the if-branch uses .then() without await)
          await new Promise((r) => setTimeout(r, 50));

          // Assert: listChats was called (getSessionList was triggered)
          expect(api.listChats).toHaveBeenCalled();
        },
      ),
      { numRuns: 50 },
    );
  });

  /**
   * Observation 3: On unfixed code, updateSession({ id: "不存在的ID" })
   * takes the else branch and refreshes sessionList.
   *
   * Test: When session id is not found in sessionList, updateSession
   * calls getSessionList (listChats) to refresh.
   */
  it("Preservation: fallback refresh when session not found in sessionList", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUUIDSessionId,
        arbUUIDSessionId,
        fc.string({ minLength: 1, maxLength: 50 }),
        async (existingId, updateId, updateName) => {
          // Pre-condition: updateId must differ from existingId
          fc.pre(updateId !== existingId);

          // Setup: sessionList has one session, but we update a different id
          setSessionList(sessionApi, [
            {
              id: existingId,
              name: "existing",
              messages: [],
              meta: {},
              sessionId: existingId,
              userId: "default",
              channel: "console",
            },
          ]);

          vi.mocked(api.listChats).mockClear();
          vi.mocked(api.listChats).mockResolvedValue([]);

          // Act: update a session that doesn't exist in sessionList
          await sessionApi.updateSession({ id: updateId, name: updateName });

          // Assert: listChats was called (else branch triggers getSessionList)
          expect(api.listChats).toHaveBeenCalled();
        },
      ),
      { numRuns: 50 },
    );
  });

  /**
   * Observation 4: On unfixed code, updateSession returns a shallow copy
   * of sessionList (not the same reference).
   *
   * Test: The returned array is a new array (different reference) but
   * contains the same session objects.
   */
  it("Preservation: updateSession returns a shallow copy of sessionList", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbUUIDSessionId,
        fc.string({ minLength: 1, maxLength: 50 }),
        async (sessionId, sessionName) => {
          // Setup: session with empty messages (not bug condition)
          setSessionList(sessionApi, [
            {
              id: sessionId,
              name: sessionName,
              messages: [],
              meta: {},
              sessionId: sessionId,
              userId: "default",
              channel: "console",
            },
          ]);

          // Act
          const result = await sessionApi.updateSession({
            id: sessionId,
            name: sessionName,
          });

          // Assert: result is an array
          expect(Array.isArray(result)).toBe(true);
          // Assert: result is NOT the same reference as internal sessionList
          expect(result).not.toBe(getSessionList(sessionApi));
          // Assert: result has the same length
          expect(result.length).toBe(getSessionList(sessionApi).length);
        },
      ),
      { numRuns: 50 },
    );
  });
});
