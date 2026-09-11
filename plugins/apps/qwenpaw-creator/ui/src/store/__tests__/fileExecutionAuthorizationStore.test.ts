import { beforeEach, describe, expect, it } from "vitest";
import { installMockFetch } from "@/test/mockFetch";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";

const pending = {
  id: "authorization-1",
  transactionId: "round-1",
  specialistRunId: "run-1",
  executionRequestId: "request-1",
  targetRef: "element:hero",
  scope: { operation: "r2v_generation" },
  status: "PENDING" as const,
  authorizationToken: "token-1",
  provider: "creator-image",
  model: "configured-image-model",
  maxCandidates: 1,
  createdAt: "now",
};

describe("file execution authorization polling", () => {
  beforeEach(() => useExecutionAuthorizationStore.getState().reset());

  it("uses project-level file routes without a SQL transaction", async () => {
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/execution-authorizations?status=PENDING",
        response: { json: { items: [pending] } },
      },
      {
        match: "/projects/p1/execution-authorizations/authorization-1/approve",
        response: { json: { ...pending, status: "APPROVED" } },
      },
    ]);

    await useExecutionAuthorizationStore.getState().load("p1");
    await useExecutionAuthorizationStore.getState().approve("authorization-1", {
      authorizationToken: "token-1",
      provider: "creator-image",
      model: "configured-image-model",
      maxCost: 0,
      maxCandidates: 1,
    });

    expect(useExecutionAuthorizationStore.getState().items[0].status).toBe(
      "APPROVED",
    );
    expect(calls.some((call) => call.url.includes("/transactions/"))).toBe(
      false,
    );
    expect(calls.at(-1)?.body).toEqual({
      authorizationToken: "token-1",
      provider: "creator-image",
      model: "configured-image-model",
      maxCost: 0,
      maxCandidates: 1,
    });
  });
});
