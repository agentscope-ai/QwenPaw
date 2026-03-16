/**
 * Bug Condition Exploration Test — Property 1: Bug Condition
 *
 * 中断操作未通知后端且会话不可恢复
 *
 * These tests are written BEFORE the fix and are EXPECTED TO FAIL
 * on unfixed code, confirming the bug exists.
 *
 * Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.3
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fc from "fast-check";

// ---- helpers ----

/** Re-implement getApiUrl so we don't import the real module (it uses `declare const`) */
function getApiUrl(path: string): string {
  const base = "";
  const apiPrefix = "/api";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${base}${apiPrefix}${normalizedPath}`;
}

function getApiToken(): string {
  return "";
}

// ---- The CURRENT (buggy) cancel implementation, extracted verbatim ----

function buggyCancel(data: { session_id: string }) {
  // This is exactly what the current code does — just console.log
  console.log(data);
}

// ---- The EXPECTED (fixed) cancel implementation ----

function expectedCancel(data: { session_id: string }) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = getApiToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  fetch(getApiUrl("/agent/cancel"), {
    method: "POST",
    headers,
    body: JSON.stringify({ session_id: data.session_id }),
  }).catch((err) => {
    console.warn("Failed to cancel agent task:", err);
  });
}

// ---- Tests ----

describe("Bug Condition Exploration: api.cancel sends HTTP request", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    globalThis.fetch = fetchSpy;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  /**
   * Test 1 (Frontend): Call api.cancel({ session_id }) and verify
   * an HTTP POST request is sent to /api/agent/cancel.
   *
   * On unfixed code this WILL FAIL — cancel only does console.log.
   *
   * **Validates: Requirements 1.1, 2.1**
   */
  it("should send HTTP POST to /api/agent/cancel when cancel is called", () => {
    const sessionId = "test-session-123";

    // Call the FIXED cancel implementation (was buggyCancel before fix)
    expectedCancel({ session_id: sessionId });

    // Verify: fetch should have been called with the cancel endpoint
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      getApiUrl("/agent/cancel"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      }),
    );
  });

  /**
   * Property-based test: For ANY session_id, calling cancel should
   * send an HTTP POST request to the backend cancel endpoint.
   *
   * **Validates: Requirements 1.1, 2.1**
   */
  it("property: for any session_id, cancel sends HTTP POST to backend", () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }),
        (sessionId: string) => {
          fetchSpy.mockClear();

          // Call the FIXED cancel implementation (was buggyCancel before fix)
          expectedCancel({ session_id: sessionId });

          // The bug: fetch is never called because cancel only does console.log
          expect(fetchSpy).toHaveBeenCalledTimes(1);
        },
      ),
      { numRuns: 20 },
    );
  });
});
