import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DecisionTray from "@/components/agent/DecisionTray";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import {
  makePendingAuthorization,
  makeReviewOperation,
  makeReviewRecord,
} from "@/test/agentFixtures";

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

const pendingAuthorization = makePendingAuthorization({
  scope: { operation: "image_generation", message: "生成开场分镜图" },
});

const textReview = (reviewId: string, pointer: string) =>
  makeReviewRecord({
    review_id: reviewId,
    round_id: `round-${reviewId}`,
    decision_token: `token-${reviewId}`,
    operations: [
      makeReviewOperation({
        json_pointer: pointer,
        before: "旧文案",
        after: "新文案",
        operation_id: `operation-${reviewId}`,
        ui_locator: { page: "plan", mediaType: "text", field: pointer },
      }),
    ],
  });

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
    decisionInFlight: false,
  });
}

afterEach(() => {
  useAgentDockUiStore.getState().reset();
  useExecutionAuthorizationStore.getState().reset();
  useFileProjectReviewStore.getState().reset();
});

describe("DecisionTray", () => {
  it("focuses the blocking authorization first, then steps to the review", () => {
    seed({ reviews: [textReview("review-1", "/description")] });
    render(<DecisionTray projectId="p1" />);

    // Blocking item focused first: only the confirmation card is expanded.
    expect(screen.getByText("生成开场分镜图")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "文本审阅 · 1 处" }),
    ).toHaveAttribute("title", expect.stringContaining("下一条"));
    expect(screen.queryByText(/旧文案/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一条决策" }));
    expect(screen.getByText(/旧文案/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一条决策" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一条决策" })).toBeEnabled();
  });

  it("shows every pending card in list mode and filters by decision kind", () => {
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

    fireEvent.click(screen.getByRole("button", { name: /^审阅 2$/ }));
    expect(screen.queryByText("生成开场分镜图")).not.toBeInTheDocument();
    expect(screen.getAllByText(/旧文案/)).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /^全部 3$/ }));
    expect(screen.getByText("生成开场分镜图")).toBeInTheDocument();
  });
});
