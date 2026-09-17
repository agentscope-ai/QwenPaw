import { describe, expect, it } from "vitest";
import { decideSubmissionAdmission } from "./submissionAdmission";

const BASE = {
  pendingDirectSubmission: false,
  targetIsCurrent: true,
  owner: true,
  frontendBusy: false,
  usesQwenPawBackend: true,
  backendStatus: "idle" as const,
};

describe("decideSubmissionAdmission", () => {
  it("allows exactly one idle submission to use the direct transport", () => {
    expect(decideSubmissionAdmission(BASE)).toBe("direct");
  });

  it.each([
    [{ pendingDirectSubmission: true }, "a previous admission is pending"],
    [{ targetIsCurrent: false }, "the page switched session or Agent"],
    [{ owner: false }, "another tab owns the conversation"],
    [{ frontendBusy: true }, "the local stream or queue is busy"],
    [{ backendStatus: "running" as const }, "the backend run is still active"],
  ])("queues when %s", (override, _reason) => {
    expect(decideSubmissionAdmission({ ...BASE, ...override })).toBe("queue");
  });

  it("does not require QwenPaw backend status for external backends", () => {
    expect(
      decideSubmissionAdmission({
        ...BASE,
        usesQwenPawBackend: false,
        backendStatus: "running",
      }),
    ).toBe("direct");
  });
});
