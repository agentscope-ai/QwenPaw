import { describe, expect, it } from "vitest";
import type { FileProjectReviewOperationDecision } from "@/contracts/creator";
import { findPendingReviewForVersion } from "../fileProjectReviewDecisions";
import { makeReviewOperation, makeReviewRecord } from "@/test/agentFixtures";

/** A media-publication operation whose locator points at one artifact version. */
const mediaOperation = (
  versionId: string,
  operationId: string,
  decision: FileProjectReviewOperationDecision = "PENDING",
) =>
  makeReviewOperation({
    kind: "create",
    json_pointer: `/assets/artifact_versions_by_id/${versionId}`,
    before: null,
    after: { version_id: versionId },
    operation_id: operationId,
    decision,
    ui_locator: {
      page: "assets",
      assetId: "cat",
      mediaType: "image",
      artifactKind: "visual_anchor",
      artifactVersionId: versionId,
    },
  });

describe("findPendingReviewForVersion", () => {
  it("returns null when there is no displayed version", () => {
    const review = makeReviewRecord({
      operations: [mediaOperation("cat-anchor-v1", "op-1")],
    });
    expect(findPendingReviewForVersion([review], null)).toBeNull();
  });

  it("finds the pending review that gates the displayed version", () => {
    const review = makeReviewRecord({
      review_id: "review-cat",
      operations: [mediaOperation("cat-anchor-v1", "op-1")],
    });
    expect(findPendingReviewForVersion([review], "cat-anchor-v1")).toBe(review);
  });

  it("returns null when no pending operation points at the version", () => {
    const review = makeReviewRecord({
      operations: [mediaOperation("cat-anchor-v1", "op-1")],
    });
    expect(findPendingReviewForVersion([review], "other-v9")).toBeNull();
  });

  it("ignores reviews that are no longer pending", () => {
    const review = makeReviewRecord({
      status: "RESOLVED",
      operations: [mediaOperation("cat-anchor-v1", "op-1")],
    });
    expect(findPendingReviewForVersion([review], "cat-anchor-v1")).toBeNull();
  });

  it("ignores operations the user already decided", () => {
    const review = makeReviewRecord({
      operations: [mediaOperation("cat-anchor-v1", "op-1", "ACCEPTED")],
    });
    expect(findPendingReviewForVersion([review], "cat-anchor-v1")).toBeNull();
  });

  it("matches the slot selection operation for the same version", () => {
    const review = makeReviewRecord({
      operations: [
        makeReviewOperation({
          kind: "update",
          json_pointer:
            "/assets/artifact_slots_by_id/visual:cat:anchor/selected_version_id",
          before: "cat-anchor-v0",
          after: "cat-anchor-v1",
          operation_id: "op-slot",
          ui_locator: {
            page: "assets",
            assetId: "cat",
            mediaType: "image",
            artifactVersionId: "cat-anchor-v1",
          },
        }),
      ],
    });
    expect(findPendingReviewForVersion([review], "cat-anchor-v1")).toBe(review);
  });

  it("returns the first matching review when several are pending", () => {
    const first = makeReviewRecord({
      review_id: "review-a",
      operations: [mediaOperation("cat-anchor-v1", "op-a")],
    });
    const second = makeReviewRecord({
      review_id: "review-b",
      operations: [mediaOperation("cat-anchor-v1", "op-b")],
    });
    expect(findPendingReviewForVersion([first, second], "cat-anchor-v1")).toBe(
      first,
    );
  });
});
