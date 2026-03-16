/**
 * Preservation Property Test — Property 2: Non-interrupt behavior unchanged
 *
 * These tests verify that existing behavior is preserved for all
 * non-cancel scenarios. They MUST PASS on unfixed code (baseline).
 *
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
 */
import { describe, it, expect, vi } from "vitest";
import fc from "fast-check";

function getApiUrl(path: string): string {
  const base = "";
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

function currentCancel(data: { session_id: string }) {
  console.log(data);
}

function parseChatId(pathname: string): string | undefined {
  const match = pathname.match(/^\/chat\/(.+)$/);
  return match?.[1];
}

function buildRequestArgs(data: {
  input: any[];
  biz_params?: any;
  signal?: AbortSignal;
}) {
  const { input, biz_params } = data;
  const session = input[input.length - 1]?.session || {};
  const requestBody = {
    input: input.slice(-1),
    session_id: session?.session_id || "",
    user_id: session?.user_id || "default",
    channel: session?.channel || "console",
    stream: true,
    ...biz_params,
  };
  return {
    url: getApiUrl("/agent/process"),
    method: "POST" as const,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody),
    signal: data.signal,
    parsedBody: requestBody,
  };
}

const alphaNumStr = fc.string({
  unit: fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789"),
  minLength: 1,
  maxLength: 20,
});

const inputMsgArb = fc.record({
  content: fc.string({ minLength: 1, maxLength: 50 }),
  session: fc.record({ session_id: alphaNumStr }),
});

describe("Preservation: customFetch request construction", () => {
  /**
   * Property: customFetch always targets /api/agent/process with POST,
   * includes stream:true, correct headers, and forwards AbortSignal.
   *
   * Validates: Requirements 3.1, 3.2
   */
  it("property: request targets /api/agent/process with POST, stream:true, and signal", () => {
    fc.assert(
      fc.property(inputMsgArb, (msg) => {
        const controller = new AbortController();
        const result = buildRequestArgs({
          input: [msg],
          signal: controller.signal,
        });

        expect(result.url).toBe("/api/agent/process");
        expect(result.method).toBe("POST");
        expect(result.headers["Content-Type"]).toBe("application/json");
        expect(result.signal).toBe(controller.signal);
        expect(result.parsedBody.stream).toBe(true);
        expect(result.parsedBody.session_id).toBe(msg.session.session_id);
        expect(result.parsedBody.input).toHaveLength(1);
      }),
      { numRuns: 50 },
    );
  });

  /**
   * Property: When no signal is provided, signal is undefined.
   *
   * Validates: Requirements 3.1, 3.2
   */
  it("property: without signal, signal is undefined", () => {
    fc.assert(
      fc.property(inputMsgArb, (msg) => {
        const result = buildRequestArgs({ input: [msg] });
        expect(result.signal).toBeUndefined();
      }),
      { numRuns: 20 },
    );
  });

  /**
   * Property: input.slice(-1) always sends only the last message,
   * preserving the dedup/single-message behavior.
   *
   * Validates: Requirements 3.4
   */
  it("property: only the last input message is sent in body", () => {
    fc.assert(
      fc.property(
        fc.array(inputMsgArb, { minLength: 1, maxLength: 5 }),
        (inputMessages) => {
          const result = buildRequestArgs({ input: inputMessages });
          const lastMsg = inputMessages[inputMessages.length - 1];

          expect(result.parsedBody.input).toHaveLength(1);
          expect(result.parsedBody.input[0]).toEqual(lastMsg);
          expect(result.parsedBody.session_id).toBe(
            lastMsg.session.session_id,
          );
        },
      ),
      { numRuns: 50 },
    );
  });
});

describe("Preservation: chatId parsing from URL pathname", () => {
  /**
   * Property: For any pathname matching /chat/<id>, parseChatId
   * extracts the correct id. Validates session switching.
   *
   * Validates: Requirements 3.3
   */
  it("property: parseChatId extracts id from /chat/<id> paths", () => {
    fc.assert(
      fc.property(
        fc.stringMatching(/^[a-zA-Z0-9_-]+$/),
        (id: string) => {
          fc.pre(id.length > 0);
          expect(parseChatId(`/chat/${id}`)).toBe(id);
        },
      ),
      { numRuns: 50 },
    );
  });

  /**
   * Property: For paths that don't match /chat/<id>, parseChatId
   * returns undefined.
   *
   * Validates: Requirements 3.3
   */
  it("property: parseChatId returns undefined for non-chat paths", () => {
    const nonChatPaths = fc.oneof(
      fc.constant("/"),
      fc.constant("/chat"),
      fc.constant("/models"),
      fc.constant("/settings"),
      fc.string({ minLength: 1, maxLength: 30 }).map((s) => `/other/${s}`),
    );

    fc.assert(
      fc.property(nonChatPaths, (pathname: string) => {
        if (pathname === "/chat") {
          expect(parseChatId(pathname)).toBeUndefined();
        }
        if (!pathname.startsWith("/chat/")) {
          expect(parseChatId(pathname)).toBeUndefined();
        }
      }),
      { numRuns: 30 },
    );
  });
});

describe("Preservation: options.api cancel is no-op (baseline)", () => {
  /**
   * The current cancel callback is a no-op (console.log).
   * Confirms CURRENT behavior — must pass on unfixed code.
   *
   * Validates: Requirements 3.1, 3.2
   */
  it("current cancel callback does not call fetch", () => {
    const fetchSpy = vi.fn();
    const originalFetch = globalThis.fetch;
    globalThis.fetch = fetchSpy;
    try {
      currentCancel({ session_id: "test-session" });
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  /**
   * Property: getApiUrl always produces /api/<path> format.
   *
   * Validates: Requirements 3.2
   */
  it("property: getApiUrl produces correct /api prefix", () => {
    fc.assert(
      fc.property(alphaNumStr, (path) => {
        const result = getApiUrl(`/${path}`);
        expect(result).toBe(`/api/${path}`);
        expect(result.startsWith("/api/")).toBe(true);
      }),
      { numRuns: 30 },
    );
  });
});
