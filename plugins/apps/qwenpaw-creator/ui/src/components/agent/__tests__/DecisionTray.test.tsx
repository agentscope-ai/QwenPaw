import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DecisionTray from "@/components/agent/DecisionTray";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

vi.mock("@/routing/locators", () => ({
  navigateToLocator: vi.fn(),
}));

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return {
    ...actual,
    getArtifactVersionMediaUrl: (versionId: string) =>
      `https://media.test/${versionId}`,
  };
});

const pendingAuthorization = {
  id: "authorization-1",
  transactionId: "round-1",
  specialistRunId: "run-1",
  executionRequestId: "request-1",
  targetRef: "element:el-1",
  scope: { operation: "image_generation", message: "生成开场分镜图" },
  status: "PENDING" as const,
  authorizationToken: "token-1",
  provider: "dashscope",
  model: "qwen-image-2.0-pro",
  maxCandidates: 1,
  createdAt: "now",
};

function textReview(
  reviewId: string,
  pointer: string,
): FileProjectReviewRecord {
  return {
    review_id: reviewId,
    round_id: `round-${reviewId}`,
    request_id: `request-${reviewId}`,
    request_message_seq: 4,
    interrupted_run_id: "run-1",
    baseline_generation: 2,
    baseline_etag: "base-2",
    candidate_generation: 3,
    candidate_etag: "candidate-3",
    decision_token: `token-${reviewId}`,
    status: "PENDING",
    operations: [
      {
        kind: "update",
        json_pointer: pointer,
        file_id: null,
        target_ref: null,
        before_hash: "before-0",
        after_hash: "after-0",
        before: "旧文案",
        after: "新文案",
        operation_id: `operation-${reviewId}`,
        ui_locator: { page: "plan", mediaType: "text", field: pointer },
        decision: "PENDING",
      },
    ],
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:01Z",
  };
}

function seed({
  authorizations = [pendingAuthorization],
  reviews = [] as FileProjectReviewRecord[],
} = {}) {
  useExecutionAuthorizationStore.setState({
    projectId: "p1",
    items: authorizations,
    error: null,
  });
  useFileProjectReviewStore.setState({
    projectId: "p1",
    reviews,
    etag: '"token"',
    syncStatus: "healthy",
    syncError: null,
    decisionInFlight: false,
  });
}

afterEach(() => {
  useAgentDockUiStore.getState().reset();
  useExecutionAuthorizationStore.getState().reset();
  useFileProjectReviewStore.getState().reset();
});

describe("DecisionTray", () => {
  it("orders the blocking authorization ahead of reviews in the stack", () => {
    seed({ reviews: [textReview("review-1", "/description")] });
    render(<DecisionTray projectId="p1" />);

    // Blocking item focused first: the production-confirmation card is fully
    // visible, review cards only show their stacked-paper stubs.
    expect(screen.getByText("生成开场分镜图")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "文本审阅 · 1 处" }),
    ).toHaveAttribute("title", expect.stringContaining("下一条"));
    expect(screen.queryByText(/旧文案/)).not.toBeInTheDocument();
  });

  it("navigates the stack with the next arrow and focuses the review card", () => {
    seed({ reviews: [textReview("review-1", "/description")] });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: "下一条决策" }));
    expect(screen.getByText(/旧文案/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一条决策" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一条决策" })).toBeEnabled();
  });

  it("shows every pending card at once in list mode", () => {
    seed({
      reviews: [
        textReview("review-1", "/description"),
        textReview("review-2", "/story/scenes/1"),
      ],
    });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: /列表/ }));
    expect(screen.getByText("生成开场分镜图")).toBeInTheDocument();
    expect(screen.getAllByText(/旧文案/)).toHaveLength(2);
    expect(screen.getByRole("button", { name: /堆叠/ })).toBeInTheDocument();
  });

  it("filters by decision kind and recovers when the filter empties", () => {
    seed({ reviews: [textReview("review-1", "/description")] });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: /^审阅 1$/ }));
    expect(screen.queryByText("生成开场分镜图")).not.toBeInTheDocument();
    expect(screen.getByText(/旧文案/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^全部 2$/ }));
    expect(screen.getByText("生成开场分镜图")).toBeInTheDocument();
  });
});
