import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import InlineReviewDiff, { matchReviewOperations } from "../InlineReviewDiff";
import type {
  FileProjectReviewOperation,
  FileProjectReviewRecord,
} from "@/contracts/creator";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

function operation(
  overrides: Partial<FileProjectReviewOperation>,
): FileProjectReviewOperation {
  return {
    kind: "update",
    json_pointer: "/strategy/creative_brief",
    file_id: null,
    target_ref: null,
    before_hash: "hash-before",
    after_hash: "hash-after",
    before: "旧文案",
    after: "新文案",
    operation_id: "operation-1",
    ui_locator: { page: "plan", mediaType: "text" },
    decision: "PENDING",
    ...overrides,
  };
}

function review(
  operations: FileProjectReviewOperation[],
  overrides: Partial<FileProjectReviewRecord> = {},
): FileProjectReviewRecord {
  return {
    review_id: "review-1",
    round_id: "round-1",
    request_id: "request-1",
    request_message_seq: 2,
    interrupted_run_id: "run-1",
    baseline_generation: 1,
    baseline_etag: "etag-base",
    candidate_generation: 2,
    candidate_etag: "etag-candidate",
    decision_token: "token-1",
    status: "PENDING",
    operations,
    created_at: "2026-07-24T00:00:00Z",
    updated_at: "2026-07-24T00:00:00Z",
    ...overrides,
  };
}

afterEach(() => {
  useFileProjectReviewStore.getState().reset();
});

describe("matchReviewOperations", () => {
  it("matches an operation whose pointer equals the field pointer", () => {
    const matches = matchReviewOperations(
      [review([operation({})])],
      "/strategy/creative_brief",
    );
    expect(matches).toHaveLength(1);
    expect(matches[0].relation).toBe("exact");
    expect(matches[0].before).toBe("旧文案");
    expect(matches[0].after).toBe("新文案");
  });

  it("extracts the field slice when an ancestor object was replaced", () => {
    const matches = matchReviewOperations(
      [
        review([
          operation({
            json_pointer: "/timelines/items/0/elements_by_id/element-1",
            before: { title: "旧标题", description: "同样" },
            after: { title: "新标题", description: "同样" },
          }),
        ]),
      ],
      "/timelines/items/0/elements_by_id/element-1/title",
    );
    expect(matches).toHaveLength(1);
    expect(matches[0].relation).toBe("ancestor");
    expect(matches[0].before).toBe("旧标题");
    expect(matches[0].after).toBe("新标题");
  });

  it("skips ancestor slices whose field value did not change", () => {
    const matches = matchReviewOperations(
      [
        review([
          operation({
            json_pointer: "/timelines/items/0/elements_by_id/element-1",
            before: { title: "旧标题", description: "同样" },
            after: { title: "新标题", description: "同样" },
          }),
        ]),
      ],
      "/timelines/items/0/elements_by_id/element-1/description",
    );
    expect(matches).toHaveLength(0);
  });

  it("reports descendant operations with their sub path", () => {
    const matches = matchReviewOperations(
      [
        review([
          operation({
            json_pointer:
              "/timelines/items/0/elements_by_id/element-1/shots/items/shot-1/description",
          }),
        ]),
      ],
      "/timelines/items/0/elements_by_id/element-1",
    );
    expect(matches).toHaveLength(1);
    expect(matches[0].relation).toBe("descendant");
    expect(matches[0].subPath).toBe("/shots/items/shot-1/description");
  });

  it("ignores resolved reviews and decided operations", () => {
    const matches = matchReviewOperations(
      [
        review([operation({ decision: "ACCEPTED" })]),
        review([operation({})], {
          review_id: "review-2",
          status: "RESOLVED",
        }),
      ],
      "/strategy/creative_brief",
    );
    expect(matches).toHaveLength(0);
  });

  it("ignores unrelated pointers", () => {
    const matches = matchReviewOperations(
      [review([operation({ json_pointer: "/strategy/creative_direction" })])],
      "/strategy/creative_brief",
    );
    expect(matches).toHaveLength(0);
  });

  it("collects rejection intent before submitting an inline undo", async () => {
    const current = review([operation({})]);
    const decide = vi.fn(async () => current);
    useFileProjectReviewStore.setState({
      projectId: "project-1",
      reviews: [current],
      decisionInFlight: false,
      decide,
    });
    render(<InlineReviewDiff pointer="/strategy/creative_brief" />);

    fireEvent.click(screen.getByRole("button", { name: "撤销该修改" }));
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "仅撤销" }));

    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith(
        "project-1",
        "review-1",
        [{ operation_id: "operation-1", decision: "REJECT" }],
        { action: "UNDO_ONLY" },
      ),
    );
  });
});
