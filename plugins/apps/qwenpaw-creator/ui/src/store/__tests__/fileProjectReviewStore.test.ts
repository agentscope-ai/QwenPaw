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

function activeResponse(value: FileProjectReviewRecord): Response {
  return response(200, [value], { ETag: `"${value.decision_token}"` });
}

function activeResponseMulti(values: FileProjectReviewRecord[]): Response {
  const compositeToken = values.map((r) => r.decision_token).join("|");
  return response(200, values, { ETag: `"${compositeToken}"` });
}

afterEach(() => {
  useFileProjectReviewStore.getState().reset();
  vi.useRealTimers();
});

describe("file-native Project Review store", () => {
  it("keeps the last-good Reviews across 304 and transient failures", async () => {
    const first = review();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(activeResponse(first))
      .mockResolvedValueOnce(response(304, undefined, { ETag: '"token-1"' }))
      .mockRejectedValueOnce(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);

    await useFileProjectReviewStore.getState().pollOnce("p1");
    const lastGood = useFileProjectReviewStore.getState().reviews;
    await useFileProjectReviewStore.getState().pollOnce("p1");
    expect(useFileProjectReviewStore.getState().reviews).toBe(lastGood);
    expect(useFileProjectReviewStore.getState().syncStatus).toBe("healthy");

    await useFileProjectReviewStore.getState().pollOnce("p1");
    expect(useFileProjectReviewStore.getState().reviews).toBe(lastGood);
    expect(useFileProjectReviewStore.getState().syncStatus).toBe("degraded");
    expect(useFileProjectReviewStore.getState().syncError).toBe("offline");
  });

  it("clears active Reviews state on both 204 and Project 404", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(activeResponse(review()))
      .mockResolvedValueOnce(response(204))
      .mockResolvedValueOnce(activeResponse(review("token-2", 4)))
      .mockResolvedValueOnce(
        response(404, { code: "NOT_FOUND", message: "gone" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await useFileProjectReviewStore.getState().pollOnce("p1");
    await useFileProjectReviewStore.getState().pollOnce("p1");
    expect(useFileProjectReviewStore.getState().reviews).toEqual([]);
    expect(useFileProjectReviewStore.getState().syncStatus).toBe("healthy");

    await useFileProjectReviewStore.getState().pollOnce("p1");
    await useFileProjectReviewStore.getState().pollOnce("p1");
    expect(useFileProjectReviewStore.getState().reviews).toEqual([]);
    expect(useFileProjectReviewStore.getState().etag).toBeNull();
    expect(useFileProjectReviewStore.getState().syncStatus).toBe("not_found");
  });

  it("does not apply a lower candidate generation over the current Reviews", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(activeResponse(review("token-5", 5)))
        .mockResolvedValueOnce(activeResponse(review("token-4", 4))),
    );

    await useFileProjectReviewStore.getState().pollOnce("p1");
    await useFileProjectReviewStore.getState().pollOnce("p1");
    expect(
      useFileProjectReviewStore.getState().reviews[0]?.candidate_generation,
    ).toBe(5);
    expect(
      useFileProjectReviewStore.getState().reviews[0]?.decision_token,
    ).toBe("token-5");
  });

  it("ignores a late response after switching Project scope", async () => {
    let resolveP1!: (value: Response) => void;
    let resolveP2!: (value: Response) => void;
    const fetchMock = vi.fn(
      (input: RequestInfo | URL) =>
        new Promise<Response>((resolve) => {
          if (String(input).includes("/projects/p1/")) resolveP1 = resolve;
          else resolveP2 = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const p1 = useFileProjectReviewStore.getState().pollOnce("p1");
    const p2 = useFileProjectReviewStore.getState().pollOnce("p2");
    resolveP2(
      activeResponse(review("p2-token", 8, { review_id: "review-p2" })),
    );
    await p2;
    resolveP1(
      activeResponse(review("p1-token", 9, { review_id: "review-p1" })),
    );
    await p1;

    expect(useFileProjectReviewStore.getState().projectId).toBe("p2");
    expect(useFileProjectReviewStore.getState().reviews[0]?.review_id).toBe(
      "review-p2",
    );
    expect(
      useFileProjectReviewStore.getState().reviews[0]?.decision_token,
    ).toBe("p2-token");
  });

  it("reuses decisionId and Idempotency-Key after an ambiguous failed response", async () => {
    const operation2 = {
      ...review().operations[0],
      json_pointer: "/story/description",
      operation_id: "operation-2",
    } as const;
    const pending = review("token-1", 3, {
      operations: [review().operations[0], operation2],
    });
    const resolved = review("token-2", 3, {
      status: "RESOLVED",
      operations: [
        { ...review().operations[0], decision: "ACCEPTED" },
        { ...operation2, decision: "ACCEPTED" },
      ],
    });
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(response(200, resolved, { ETag: '"token-2"' }));
    vi.stubGlobal("fetch", fetchMock);
    useFileProjectReviewStore.setState({
      projectId: "p1",
      reviews: [pending],
      etag: '"token-1"',
      syncStatus: "healthy",
    });
    const decisions = [
      { operation_id: "operation-2", decision: "ACCEPT" as const },
      { operation_id: "operation-1", decision: "ACCEPT" as const },
    ];

    await expect(
      useFileProjectReviewStore.getState().decide("p1", "review-1", decisions),
    ).rejects.toThrow("response lost");
    await expect(
      useFileProjectReviewStore
        .getState()
        .decide("p1", "review-1", [...decisions].reverse()),
    ).resolves.toMatchObject({ status: "RESOLVED" });

    const firstInit = fetchMock.mock.calls[0][1] as RequestInit;
    const secondInit = fetchMock.mock.calls[1][1] as RequestInit;
    const firstBody = JSON.parse(String(firstInit.body));
    const secondBody = JSON.parse(String(secondInit.body));
    expect(firstBody.decisionId).toBe(secondBody.decisionId);
    expect(firstBody.decisions).toEqual(secondBody.decisions);
    expect(new Headers(firstInit.headers).get("Idempotency-Key")).toBe(
      firstBody.decisionId,
    );
    expect(new Headers(secondInit.headers).get("Idempotency-Key")).toBe(
      firstBody.decisionId,
    );
    expect(useFileProjectReviewStore.getState().reviews).toEqual([]);
  });

  it("includes rejection feedback in the stable retry identity", async () => {
    const pending = review();
    const resolved = review("token-2", 4, {
      status: "RESOLVED",
      operations: [{ ...review().operations[0], decision: "REJECTED" }],
    });
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(response(200, resolved));
    vi.stubGlobal("fetch", fetchMock);
    useFileProjectReviewStore.setState({
      projectId: "p1",
      reviews: [pending],
      etag: '"token-1"',
      syncStatus: "healthy",
    });
    const decisions = [
      { operation_id: "operation-1", decision: "REJECT" as const },
    ];
    const feedback = {
      action: "UNDO_AND_REGENERATE" as const,
      problemNote: "人物状态不对",
      regenerationInstruction: "保持身份一致",
    };

    await expect(
      useFileProjectReviewStore
        .getState()
        .decide("p1", "review-1", decisions, feedback),
    ).rejects.toThrow("response lost");
    await expect(
      useFileProjectReviewStore
        .getState()
        .decide("p1", "review-1", decisions, feedback),
    ).resolves.toMatchObject({ status: "RESOLVED" });

    const firstBody = JSON.parse(
      String((fetchMock.mock.calls[0][1] as RequestInit).body),
    );
    const secondBody = JSON.parse(
      String((fetchMock.mock.calls[1][1] as RequestInit).body),
    );
    expect(firstBody.decisionId).toBe(secondBody.decisionId);
    expect(firstBody.rejectionFeedback).toEqual(feedback);
    expect(secondBody.rejectionFeedback).toEqual(feedback);
  });

  it("handles multiple pending reviews in FIFO order", async () => {
    const first = review("token-1", 3, {
      review_id: "review-1",
      created_at: "2026-07-15T00:00:00Z",
    });
    const second = review("token-2", 4, {
      review_id: "review-2",
      created_at: "2026-07-15T00:00:01Z",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(activeResponseMulti([first, second]));
    vi.stubGlobal("fetch", fetchMock);

    await useFileProjectReviewStore.getState().pollOnce("p1");
    const reviews = useFileProjectReviewStore.getState().reviews;
    expect(reviews).toHaveLength(2);
    expect(reviews[0].review_id).toBe("review-1");
    expect(reviews[1].review_id).toBe("review-2");
  });
});
