import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FileProjectReviewPanel from "@/components/agent/FileProjectReviewPanel";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { makeReviewOperation, makeReviewRecord } from "@/test/agentFixtures";

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

const review = (operationCount = 1) =>
  makeReviewRecord({
    operations: Array.from({ length: operationCount }, (_, index) => {
      const pointer = index === 0 ? "/description" : `/story/scenes/${index}`;
      return makeReviewOperation({
        json_pointer: pointer,
        before: index === 0 ? "Old title" : { index, enabled: false },
        after: index === 0 ? "New title" : { index, enabled: true },
        operation_id: `operation-${index + 1}`,
        ui_locator: { page: "plan", mediaType: "text", field: pointer },
      });
    }),
  });

const mediaReview = () =>
  makeReviewRecord({
    operations: [
      makeReviewOperation({
        json_pointer:
          "/assets/artifact_slots_by_id/element:el-1:main/selected_version_id",
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
      }),
    ],
  });

/** Seeds the review store and renders the panel; returns the decide spy. */
function setup(value = review(), decide = vi.fn(async () => value)) {
  useFileProjectReviewStore.setState({
    projectId: "p1",
    reviews: [value],
    etag: '"token-1"',
    syncStatus: "healthy",
    syncError: null,
    decisionInFlight: false,
    decide,
  });
  render(<FileProjectReviewPanel projectId="p1" review={value} />);
  return decide;
}

afterEach(() => {
  useFileProjectReviewStore.getState().reset();
  navigateToLocator.mockClear();
});

describe("FileProjectReviewPanel", () => {
  it("renders a text summary and navigates to the ui_locator on inspect", () => {
    setup();
    expect(screen.getByText("文件项目修改")).toBeInTheDocument();
    // Text changes render only a summary; the full diff shows via "查看".
    expect(screen.getByTitle("/description")).toBeInTheDocument();
    expect(document.querySelector("[data-review-diff]")).toBeNull();
    expect(screen.queryByText("New title")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "查看 /description" }));
    expect(navigateToLocator).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ field: "/description" }),
      expect.objectContaining({ review: true, field: "/description" }),
    );
  });

  it("submits an individual Keep decision by operation_id", async () => {
    const decide = setup();

    fireEvent.click(screen.getByRole("button", { name: "保留 /description" }));
    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith("p1", "review-1", [
        { operation_id: "operation-1", decision: "ACCEPT" },
      ]),
    );
  });

  it("opens feedback before undoing all pending operations", async () => {
    const decide = setup(review(2));

    fireEvent.click(screen.getByRole("button", { name: "全部撤销" }));
    expect(decide).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("撤销 2 项内容");
    fireEvent.click(screen.getByRole("button", { name: "仅撤销" }));
    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith(
        "p1",
        "review-1",
        [
          { operation_id: "operation-1", decision: "REJECT" },
          { operation_id: "operation-2", decision: "REJECT" },
        ],
        { action: "UNDO_ONLY" },
      ),
    );
  });

  it("submits structured feedback when undo and regenerate is selected", async () => {
    const decide = setup();

    fireEvent.click(screen.getByRole("button", { name: "撤销 /description" }));
    const feedback = screen.getByRole("textbox", { name: "反馈与调整要求" });
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.queryByRole("textbox", { name: "哪里不对" })).toBeNull();
    fireEvent.change(feedback, {
      target: { value: "人物状态不对；保持身份一致，改成落魄时期" },
    });
    const regenerate = screen.getByRole("button", { name: "撤销并重做" });
    fireEvent.click(regenerate);
    fireEvent.click(regenerate);

    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith(
        "p1",
        "review-1",
        [{ operation_id: "operation-1", decision: "REJECT" }],
        {
          action: "UNDO_AND_REGENERATE",
          feedbackNote: "人物状态不对；保持身份一致，改成落魄时期",
        },
      ),
    );
    expect(decide).toHaveBeenCalledTimes(1);
  });

  it("renders a media preview and opens the generation detail locator", () => {
    setup(mediaReview());
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
