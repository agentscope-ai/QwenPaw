import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import InlineReviewDiff, { matchReviewOperations } from "../InlineReviewDiff";
import type {
  FileProjectReviewOperation,
  FileProjectReviewRecord,
} from "@/contracts/creator";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { makeReviewOperation, makeReviewRecord } from "@/test/agentFixtures";
import DiffView from "@/components/agent/DiffView";

const operation = (overrides: Partial<FileProjectReviewOperation>) =>
  makeReviewOperation({
    json_pointer: "/strategy/creative_brief",
    before: "旧文案",
    after: "新文案",
    ui_locator: { page: "plan", mediaType: "text" },
    ...overrides,
  });

const review = (
  operations: FileProjectReviewOperation[],
  overrides: Partial<FileProjectReviewRecord> = {},
) => makeReviewRecord({ operations, ...overrides });

// One replaced Element object shared by both ancestor-slice tests.
const elementReplaced = review([
  operation({
    json_pointer: "/timelines/items/0/elements_by_id/element-1",
    before: { title: "旧标题", description: "同样" },
    after: { title: "新标题", description: "同样" },
  }),
]);

afterEach(() => {
  useFileProjectReviewStore.getState().reset();
});

describe("matchReviewOperations", () => {
  it("matches an exact pointer and ignores unrelated ones", () => {
    const matches = matchReviewOperations(
      [review([operation({})])],
      "/strategy/creative_brief",
    );
    expect(matches).toHaveLength(1);
    expect(matches[0].relation).toBe("exact");
    expect(matches[0].before).toBe("旧文案");
    expect(matches[0].after).toBe("新文案");
    expect(
      matchReviewOperations(
        [review([operation({ json_pointer: "/strategy/creative_direction" })])],
        "/strategy/creative_brief",
      ),
    ).toHaveLength(0);
  });

  it("extracts only the changed field slice when an ancestor object was replaced", () => {
    const matches = matchReviewOperations(
      [elementReplaced],
      "/timelines/items/0/elements_by_id/element-1/title",
    );
    expect(matches).toHaveLength(1);
    expect(matches[0].relation).toBe("ancestor");
    expect(matches[0].before).toBe("旧标题");
    expect(matches[0].after).toBe("新标题");
    // The untouched sibling field yields no match.
    expect(
      matchReviewOperations(
        [elementReplaced],
        "/timelines/items/0/elements_by_id/element-1/description",
      ),
    ).toHaveLength(0);
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

describe("DiffView", () => {
  it("renders removed and added lines for text changes", () => {
    render(<DiffView before={"alpha\nbeta"} after={"alpha\ngamma"} />);
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.getByText("gamma")).toBeInTheDocument();
    expect(document.querySelector('[data-diff-kind="removed"]')).toBeTruthy();
    expect(document.querySelector('[data-diff-kind="added"]')).toBeTruthy();
  });

  it("shows an empty-state message when both sides are empty", () => {
    render(<DiffView before={null} after={null} />);
    expect(screen.getByText("（无内容变化）")).toBeInTheDocument();
  });
});
