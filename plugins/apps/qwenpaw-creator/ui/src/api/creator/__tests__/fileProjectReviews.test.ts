import { describe, expect, it, vi } from "vitest";
import {
  decideFileProjectReview,
  getActiveFileProjectReview,
  parseFileProjectReview,
} from "@/api/creator";

function review(overrides: Record<string, unknown> = {}) {
  return {
    review_id: "review-1",
    round_id: "round-1",
    request_id: "request-1",
    request_message_seq: 4,
    interrupted_run_id: "run-1",
    baseline_generation: 2,
    baseline_etag: "base-2",
    candidate_generation: 3,
    candidate_etag: "candidate-3",
    decision_token: "token-1",
    status: "PENDING",
    operations: [
      {
        kind: "update",
        json_pointer: "/story/title",
        file_id: null,
        target_ref: null,
        before_hash: "before-hash",
        after_hash: "after-hash",
        before: "Old title",
        after: "New title",
        operation_id: "operation-1",
        ui_locator: { route: "/project/p1/plan" },
        decision: "PENDING",
      },
    ],
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:01Z",
    ...overrides,
  };
}

function response(
  status: number,
  body?: unknown,
  headers: Record<string, string> = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 304 ? "Not Modified" : "OK",
    headers: new Headers(headers),
    json: vi.fn(async () => body),
  } as unknown as Response;
}

describe("file-native Project Review API", () => {
  it("reads the strict snake_case contract and treats 204/304 as protocol results", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(200, [review()], { ETag: '"token-1"' }))
      .mockResolvedValueOnce(response(204))
      .mockResolvedValueOnce(response(304, undefined, { ETag: '"token-1"' }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getActiveFileProjectReview("p1")).resolves.toMatchObject({
      kind: "updated",
      etag: '"token-1"',
      reviews: [
        {
          review_id: "review-1",
          candidate_generation: 3,
          decision_token: "token-1",
        },
      ],
    });
    await expect(getActiveFileProjectReview("p1")).resolves.toEqual({
      kind: "empty",
    });
    await expect(
      getActiveFileProjectReview("p1", '"token-1"'),
    ).resolves.toEqual({
      kind: "not_modified",
      etag: '"token-1"',
    });
    expect(
      new Headers(fetchMock.mock.calls[2][1].headers).get("If-None-Match"),
    ).toBe('"token-1"');
  });

  it("posts operation decisions with camel request metadata and an Idempotency-Key", async () => {
    const resolved = review({
      decision_token: "token-2",
      status: "RESOLVED",
      operations: [
        {
          ...review().operations[0],
          decision: "ACCEPTED",
        },
      ],
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init: RequestInit = {}) =>
        response(200, resolved),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      decideFileProjectReview(
        "p1",
        "review-1",
        {
          decisionId: "decision-1",
          decisionToken: "token-1",
          decisions: [{ operation_id: "operation-1", decision: "ACCEPT" }],
        },
        "idempotency-1",
      ),
    ).resolves.toMatchObject({ status: "RESOLVED" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      "/api/qwenpaw-creator/projects/p1/runtime/reviews/review-1/decisions",
    );
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe(
      "idempotency-1",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      decisionId: "decision-1",
      decisionToken: "token-1",
      decisions: [{ operation_id: "operation-1", decision: "ACCEPT" }],
    });
  });

  it("rejects malformed operations instead of exposing an untyped payload", () => {
    const malformed = review({
      operations: [{ ...review().operations[0], json_pointer: "story/title" }],
    });
    expect(() => parseFileProjectReview(malformed)).toThrow("JSON Pointer");
  });
});
