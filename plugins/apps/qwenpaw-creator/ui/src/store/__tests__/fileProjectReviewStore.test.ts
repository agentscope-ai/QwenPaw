import { afterEach, describe, expect, it, vi } from "vitest";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

function review(
  token = "token-1",
  generation = 3,
  overrides: Partial<FileProjectReviewRecord> = {},
): FileProjectReviewRecord {
  return {
    review_id: "review-1",
    round_id: "round-1",
    request_id: "request-1",
    request_message_seq: 4,
    interrupted_run_id: "run-1",
    baseline_generation: 2,
    baseline_etag: "base-2",
    candidate_generation: generation,
    candidate_etag: `candidate-${generation}`,
    decision_token: token,
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
        ui_locator: {},
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
    statusText: status === 404 ? "Not Found" : "OK",
    headers: new Headers(headers),
    json: vi.fn(async () => body),
  } as unknown as Response;
}

const activeResponse = (...values: FileProjectReviewRecord[]) =>
  response(200, values, {
    ETag: `"${values.map((value) => value.decision_token).join("|")}"`,
  });

const store = () => useFileProjectReviewStore.getState();
const poll = (projectId = "p1") => store().pollOnce(projectId);
const seed = (reviews: FileProjectReviewRecord[]) =>
  useFileProjectReviewStore.setState({
    projectId: "p1",
    reviews,
    etag: '"token-1"',
    syncStatus: "healthy",
  });
const bodyOf = (mock: ReturnType<typeof vi.fn>, index: number) =>
  JSON.parse(String((mock.mock.calls[index][1] as RequestInit).body));
const headerOf = (
  mock: ReturnType<typeof vi.fn>,
  index: number,
  name: string,
) => new Headers((mock.mock.calls[index][1] as RequestInit).headers).get(name);

afterEach(() => store().reset());

describe("file-native Project Review store", () => {
  it("keeps last-good on 304/errors and clears on 204/404 (fail-closed sync)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(activeResponse(review()))
      .mockResolvedValueOnce(response(304, undefined, { ETag: '"token-1"' }))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(response(204))
      .mockResolvedValueOnce(activeResponse(review("token-2", 4)))
      .mockResolvedValueOnce(
        response(404, { code: "NOT_FOUND", message: "gone" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await poll();
    const lastGood = store().reviews;
    await poll();
    expect(store().reviews).toBe(lastGood);
    expect(store().syncStatus).toBe("healthy");
    await poll();
    expect(store().reviews).toBe(lastGood);
    expect(store()).toMatchObject({
      syncStatus: "degraded",
      syncError: "offline",
    });
    await poll();
    expect(store()).toMatchObject({ reviews: [], syncStatus: "healthy" });
    await poll();
    await poll();
    expect(store().reviews).toEqual([]);
    expect(store().etag).toBeNull();
    expect(store().syncStatus).toBe("not_found");
  });

  it("orders pending reviews FIFO and never applies a lower candidate generation", async () => {
    const second = review("token-2", 4, {
      review_id: "review-2",
      created_at: "2026-07-15T00:00:01Z",
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(activeResponse(review("token-5", 5), second))
        .mockResolvedValueOnce(activeResponse(review("token-4", 4))),
    );

    await poll();
    expect(store().reviews.map((item) => item.review_id)).toEqual([
      "review-1",
      "review-2",
    ]);
    await poll();
    expect(store().reviews[0]).toMatchObject({
      candidate_generation: 5,
      decision_token: "token-5",
    });
  });

  it("ignores a late response after switching Project scope", async () => {
    let resolveP1!: (value: Response) => void;
    let resolveP2!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (input: RequestInfo | URL) =>
          new Promise<Response>((resolve) => {
            if (String(input).includes("/projects/p1/")) resolveP1 = resolve;
            else resolveP2 = resolve;
          }),
      ),
    );

    const p1 = poll("p1");
    const p2 = poll("p2");
    resolveP2(
      activeResponse(review("p2-token", 8, { review_id: "review-p2" })),
    );
    await p2;
    resolveP1(
      activeResponse(review("p1-token", 9, { review_id: "review-p1" })),
    );
    await p1;

    expect(store().projectId).toBe("p2");
    expect(store().reviews[0]?.review_id).toBe("review-p2");
  });

  it("reuses decisionId, Idempotency-Key and feedback across an ambiguous retry", async () => {
    const op1 = review().operations[0];
    const operation2 = {
      ...op1,
      json_pointer: "/story/description",
      operation_id: "operation-2",
    } as const;
    const resolved = review("token-2", 3, {
      status: "RESOLVED",
      operations: [
        { ...op1, decision: "ACCEPTED" },
        { ...operation2, decision: "REJECTED" },
      ],
    });
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(response(200, resolved, { ETag: '"token-2"' }));
    vi.stubGlobal("fetch", fetchMock);
    seed([review("token-1", 3, { operations: [op1, operation2] })]);
    const decisions = [
      { operation_id: "operation-2", decision: "REJECT" as const },
      { operation_id: "operation-1", decision: "ACCEPT" as const },
    ];
    const feedback = {
      action: "UNDO_AND_REGENERATE" as const,
      problemNote: "人物状态不对",
      regenerationInstruction: "保持身份一致",
    };

    await expect(
      store().decide("p1", "review-1", decisions, feedback),
    ).rejects.toThrow("response lost");
    await expect(
      store().decide("p1", "review-1", [...decisions].reverse(), feedback),
    ).resolves.toMatchObject({ status: "RESOLVED" });

    const firstBody = bodyOf(fetchMock, 0);
    const secondBody = bodyOf(fetchMock, 1);
    expect(firstBody.decisionId).toBe(secondBody.decisionId);
    expect(firstBody.decisions).toEqual(secondBody.decisions);
    expect(firstBody.rejectionFeedback).toEqual(feedback);
    expect(secondBody.rejectionFeedback).toEqual(feedback);
    for (const index of [0, 1]) {
      expect(headerOf(fetchMock, index, "Idempotency-Key")).toBe(
        firstBody.decisionId,
      );
    }
    expect(store().reviews).toEqual([]);
  });
});
