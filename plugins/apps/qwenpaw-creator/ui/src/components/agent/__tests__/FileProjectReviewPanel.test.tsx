import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FileProjectReviewPanel from "@/components/agent/FileProjectReviewPanel";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

const navigateToLocator = vi.fn();

vi.mock("@/routing/locators", () => ({
  navigateToLocator: (...args: unknown[]) => navigateToLocator(...args),
}));

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return {
    ...actual,
    getArtifactVersionMediaUrl: (versionId: string) =>
      `https://media.test/${versionId}`,
  };
});

function review(operationCount = 1): FileProjectReviewRecord {
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
    operations: Array.from({ length: operationCount }, (_, index) => ({
      kind: "update",
      json_pointer: index === 0 ? "/description" : `/story/scenes/${index}`,
      file_id: null,
      target_ref: null,
      before_hash: `before-${index}`,
      after_hash: `after-${index}`,
      before: index === 0 ? "Old title" : { index, enabled: false },
      after: index === 0 ? "New title" : { index, enabled: true },
      operation_id: `operation-${index + 1}`,
      ui_locator: {
        page: "plan",
        mediaType: "text",
        field: index === 0 ? "/description" : `/story/scenes/${index}`,
      },
      decision: "PENDING",
    })),
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:01Z",
  };
}

function mediaReview(): FileProjectReviewRecord {
  return {
    ...review(),
    operations: [
      {
        kind: "update",
        json_pointer:
          "/assets/artifact_slots_by_id/element:el-1:main/selected_version_id",
        file_id: null,
        target_ref: null,
        before_hash: "before-media",
        after_hash: "after-media",
        before: "ver-old",
        after: "ver-new",
        operation_id: "operation-media",
        ui_locator: {
          page: "element",
          elementId: "el-1",
          mediaType: "video",
          artifactKind: "r2v_video",
          artifactVersionId: "ver-new",
        },
        decision: "PENDING",
      },
    ],
  };
}

function seed(
  value: FileProjectReviewRecord,
  decide = vi.fn(async () => value),
) {
  useFileProjectReviewStore.setState({
    projectId: "p1",
    reviews: [value],
    etag: '"token-1"',
    syncStatus: "healthy",
    syncError: null,
    decisionInFlight: false,
    decide,
  });
  return decide;
}

afterEach(() => {
  useFileProjectReviewStore.getState().reset();
  navigateToLocator.mockClear();
});

describe("FileProjectReviewPanel", () => {
  it("renders the review panel with the provided review", () => {
    seed(review());
    const reviewData = review();
    render(<FileProjectReviewPanel projectId="p1" review={reviewData} />);
    expect(screen.getByText("文件项目修改")).toBeInTheDocument();
    // Text changes no longer render a diff inside the review panel; only a
    // readable summary is shown, and the full diff appears at the original
    // location via the "查看" (view) jump.
    expect(screen.getByText("描述")).toBeInTheDocument();
    expect(screen.getByTitle("/description")).toBeInTheDocument();
    expect(document.querySelector("[data-review-diff]")).toBeNull();
    expect(screen.queryByText("Old title")).toBeNull();
    expect(screen.queryByText("New title")).toBeNull();
  });

  it("submits an individual Keep decision by operation_id", async () => {
    const decide = seed(review());
    const reviewData = review();
    render(<FileProjectReviewPanel projectId="p1" review={reviewData} />);

    fireEvent.click(screen.getByRole("button", { name: "保留 /description" }));
    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith("p1", "review-1", [
        {
          operation_id: "operation-1",
          decision: "ACCEPT",
        },
      ]),
    );
  });

  it("submits all pending operations in one Undo all request", async () => {
    const value = review(2);
    const decide = seed(value);
    render(<FileProjectReviewPanel projectId="p1" review={value} />);

    fireEvent.click(screen.getByRole("button", { name: "全部撤销" }));
    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith("p1", "review-1", [
        { operation_id: "operation-1", decision: "REJECT" },
        { operation_id: "operation-2", decision: "REJECT" },
      ]),
    );
  });

  it("navigates to the ui_locator when a text operation is inspected", () => {
    seed(review());
    const reviewData = review();
    render(<FileProjectReviewPanel projectId="p1" review={reviewData} />);
    fireEvent.click(screen.getByRole("button", { name: "查看 /description" }));
    expect(navigateToLocator).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ field: "/description" }),
      expect.objectContaining({ review: true, field: "/description" }),
    );
  });

  it("renders a media preview and opens the generation detail locator", () => {
    seed(mediaReview());
    const reviewData = mediaReview();
    render(<FileProjectReviewPanel projectId="p1" review={reviewData} />);
    expect(screen.getByText("视频审阅")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看生成详情" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "查看生成详情" }));
    expect(navigateToLocator).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({
        page: "element",
        elementId: "el-1",
        artifactVersionId: "ver-new",
      }),
      expect.objectContaining({ review: true }),
    );
  });
});
