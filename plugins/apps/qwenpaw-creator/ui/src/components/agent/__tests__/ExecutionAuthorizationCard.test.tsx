import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { message } from "antd";
import ExecutionAuthorizationCard from "@/components/agent/ExecutionAuthorizationCard";
import { CreatorHttpError } from "@/api/creator/client";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useDecisionFocusStore } from "@/store/decisionFocusStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import {
  useProjectSnapshotStore,
  type ProjectSnapshotState,
} from "@/store/projectSnapshotStore";
import { projectDocument } from "@/test/creatorFixtures";
import { makePendingAuthorization } from "@/test/agentFixtures";

vi.mock("@/routing/locators", () => ({ navigateToLocator: vi.fn() }));

type PatchFn = ProjectSnapshotState["patch"];

const STORYBOARD_POINTER =
  "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/storyboard_prompt";

function seed(patch: PatchFn) {
  useProjectSnapshotStore.setState({
    projectId: "p1",
    project: projectDocument,
    generation: 3,
    etag: "etag-3",
    patching: false,
    patch,
  });
  useExecutionAuthorizationStore.setState({ projectId: "p1" });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useExecutionAuthorizationStore.getState().reset();
  useProjectSnapshotStore.getState().reset();
  useFileProjectReviewStore.getState().reset();
  useDecisionFocusStore.getState().clear();
});

describe("ExecutionAuthorizationCard inline prompt editing", () => {
  it("does not approve a refreshed snapshot while an untouched old draft is visible", () => {
    seed(vi.fn());
    const approve = vi.fn();
    useExecutionAuthorizationStore.setState({ approve });
    const authorization = makePendingAuthorization({
      targetRef: "element:r2v-window",
      scope: {
        operation: "image_generation",
        workGraph: { nodeId: "storyboard:r2v-window" },
      },
    });
    const view = render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));
    const newer = structuredClone(projectDocument);
    Object.assign(
      newer.timelines.items["timeline:main"].elements_by_id["r2v-window"]
        .creation,
      {
        storyboard_prompt: "另一个编辑入口保存的内容",
      },
    );
    act(() =>
      useProjectSnapshotStore.setState({ project: newer, etag: '"etag-4"' }),
    );
    view.rerender(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={newer}
      />,
    );
    expect(screen.getByRole("textbox")).toHaveValue("暖色餐厅窗外的橘猫");
    const proceed = screen.getByRole("button", { name: "继续" });
    // F1/F2: the primary confirmation action shares the decision-button style.
    expect(proceed).toHaveClass("btn-decision");
    expect(proceed).toHaveAttribute("data-execution-auth-continue", "");
    expect(proceed).toBeDisabled();
    fireEvent.click(proceed);
    expect(approve).not.toHaveBeenCalled();
    expect(screen.getByText(/此提示词已在其他位置更新/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));
    expect(proceed).toBeEnabled();
  });
  it("edits and CAS-saves the target prompt before confirming generation", async () => {
    const patchMock = vi.fn(async () => ({
      project: projectDocument,
      generation: 4,
      etag: "etag-4",
    }));
    seed(patchMock as unknown as PatchFn);
    const authorization = makePendingAuthorization({
      targetRef: "element:r2v-window",
      scope: { operation: "image_generation" },
    });

    render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={projectDocument}
      />,
    );

    // The editor stays collapsed until requested; the toggle is offered only
    // for production confirmations that resolve to a concrete prompt field.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));

    const textarea = screen.getByDisplayValue("暖色餐厅窗外的橘猫");
    // Save is inert until the draft actually diverges from the stored value.
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    fireEvent.change(textarea, { target: { value: "暖色窗边打盹的橘猫" } });

    const save = screen.getByRole("button", { name: "保存" });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));
    expect(patchMock).toHaveBeenCalledWith("p1", [
      expect.objectContaining({
        op: "replace",
        path: STORYBOARD_POINTER,
        before: "暖色餐厅窗外的橘猫",
        value: "暖色窗边打盹的橘猫",
      }),
    ]);
    // A successful save collapses the editor so the card returns to confirm.
    await waitFor(() =>
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument(),
    );
  });

  it("discards an in-progress edit without patching", async () => {
    const patchMock = vi.fn(async () => ({
      project: projectDocument,
      generation: 4,
      etag: "etag-4",
    }));
    seed(patchMock as unknown as PatchFn);
    const authorization = makePendingAuthorization({
      targetRef: "element:r2v-window",
      scope: { operation: "image_generation" },
    });

    render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={projectDocument}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));
    fireEvent.change(screen.getByDisplayValue("暖色餐厅窗外的橘猫"), {
      target: { value: "临时改动" },
    });
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("does not offer prompt editing on a content checkpoint card", () => {
    seed(vi.fn() as unknown as PatchFn);
    const authorization = makePendingAuthorization({
      targetRef: "timeline:main",
      scope: { operation: "creation_checkpoint_script" },
    });

    render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={projectDocument}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "编辑提示词" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("keeps the original edit baseline after a concurrent snapshot update", async () => {
    const patchMock = vi.fn().mockRejectedValue(new Error("conflict"));
    seed(patchMock);
    const authorization = makePendingAuthorization({
      targetRef: "element:r2v-window",
      scope: { operation: "image_generation" },
    });
    const view = render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "我的草稿" },
    });
    const newer = structuredClone(projectDocument);
    Object.assign(
      newer.timelines.items["timeline:main"].elements_by_id["r2v-window"]
        .creation,
      {
        storyboard_prompt: "另一位编辑的新提示词",
      },
    );
    act(() =>
      useProjectSnapshotStore.setState({
        project: newer,
        generation: 4,
        etag: "etag-4",
      }),
    );
    view.rerender(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={newer}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));
    expect(patchMock).toHaveBeenCalledWith("p1", [
      expect.objectContaining({
        path: STORYBOARD_POINTER,
        before: "暖色餐厅窗外的橘猫",
        value: "我的草稿",
      }),
    ]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "保存" })).toBeEnabled(),
    );
    expect(screen.getByRole("textbox")).toHaveValue("我的草稿");
    expect(useProjectSnapshotStore.getState().project).toBe(newer);
  });

  it("does not approve an unsaved draft", () => {
    seed(vi.fn());
    const approve = vi.fn();
    useExecutionAuthorizationStore.setState({ approve });
    render(
      <ExecutionAuthorizationCard
        authorization={makePendingAuthorization({
          targetRef: "element:r2v-window",
          scope: { operation: "image_generation" },
        })}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "尚未保存" },
    });
    const proceed = screen.getByRole("button", { name: "继续" });
    expect(proceed).toBeDisabled();
    fireEvent.click(proceed);
    expect(approve).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "放弃" }));
    expect(proceed).toBeEnabled();
  });

  it("approves the saved snapshot even after the card is remounted", async () => {
    const newer = structuredClone(projectDocument);
    Object.assign(
      newer.timelines.items["timeline:main"].elements_by_id["r2v-window"]
        .creation,
      {
        storyboard_prompt: "已保存的新提示词",
      },
    );
    const patchMock = vi.fn(async () => {
      useProjectSnapshotStore.setState({
        project: newer,
        generation: 4,
        etag: "etag-4",
      });
      return { project: newer, generation: 4, etag: "etag-4" };
    });
    seed(patchMock as unknown as PatchFn);
    const approve = vi.fn().mockResolvedValue(undefined);
    useExecutionAuthorizationStore.setState({ approve });
    const authorization = makePendingAuthorization({
      targetRef: "element:r2v-window",
      scope: {
        operation: "image_generation",
        workGraph: { nodeId: "storyboard:r2v-window" },
      },
    });
    const view = render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "已保存的新提示词" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument(),
    );
    view.unmount();
    render(
      <ExecutionAuthorizationCard
        authorization={authorization}
        project={newer}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() =>
      expect(approve).toHaveBeenCalledWith(
        authorization.id,
        expect.objectContaining({ projectEtag: "etag-4" }),
      ),
    );
  });

  it.each(["non-workgraph", "stale-card"])(
    "binds legacy prompts but does not rebind a stale card: %s",
    async (kind) => {
      seed(vi.fn());
      const approve = vi.fn().mockResolvedValue(undefined);
      useExecutionAuthorizationStore.setState({ approve });
      const authorization = makePendingAuthorization({
        targetRef: "element:r2v-window",
        scope: {
          operation: "image_generation",
          ...(kind === "stale-card"
            ? { workGraph: { nodeId: "storyboard:r2v-window" } }
            : {}),
        },
      });
      if (kind === "stale-card") {
        useProjectSnapshotStore.setState({
          project: structuredClone(projectDocument),
          etag: "etag-4",
        });
      }
      render(
        <ExecutionAuthorizationCard
          authorization={authorization}
          project={projectDocument}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "继续" }));
      if (kind === "non-workgraph") {
        await waitFor(() => expect(approve).toHaveBeenCalledTimes(1));
        expect(approve.mock.calls[0][1]).toHaveProperty(
          "projectEtag",
          "etag-3",
        );
        expect(approve.mock.calls[0][1]).toHaveProperty(
          "promptPointer",
          STORYBOARD_POINTER,
        );
      } else {
        expect(approve).not.toHaveBeenCalled();
      }
    },
  );

  it("locks the open editor while approval is in flight", async () => {
    seed(vi.fn());
    let finish!: () => void;
    const approve = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    useExecutionAuthorizationStore.setState({ approve });
    render(
      <ExecutionAuthorizationCard
        authorization={makePendingAuthorization({
          targetRef: "element:r2v-window",
          scope: { operation: "image_generation" },
        })}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑提示词" }));
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "放弃" })).toBeDisabled();
    await act(async () => finish());
  });

  it("renders the snapshot conflict inline and refreshes instead of a toast", async () => {
    seed(vi.fn());
    const pollOnce = vi.fn().mockResolvedValue(undefined);
    useProjectSnapshotStore.setState({
      pollOnce: pollOnce as unknown as ProjectSnapshotState["pollOnce"],
    });
    const warning = vi
      .spyOn(message, "warning")
      .mockImplementation(() => undefined as never);
    const error = vi
      .spyOn(message, "error")
      .mockImplementation(() => undefined as never);
    const approve = vi
      .fn()
      .mockRejectedValueOnce(
        new CreatorHttpError(409, {
          message: "已保存的项目快照已改变，请重新保存后批准",
        }),
      )
      .mockRejectedValueOnce(new Error("network"));
    useExecutionAuthorizationStore.setState({ approve });
    render(
      <ExecutionAuthorizationCard
        authorization={makePendingAuthorization({
          targetRef: "element:r2v-window",
          scope: {
            operation: "image_generation",
            workGraph: { nodeId: "storyboard:r2v-window" },
          },
        })}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() =>
      expect(
        document.querySelector("[data-execution-auth-error]"),
      ).not.toBeNull(),
    );
    expect(
      document.querySelector("[data-execution-auth-error]"),
    ).toHaveTextContent("已保存的项目快照已改变，请重新保存后批准");
    expect(warning).not.toHaveBeenCalled();
    expect(pollOnce).toHaveBeenCalledWith("p1");
    expect(error).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "关闭错误提示" }));
    expect(document.querySelector("[data-execution-auth-error]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() => expect(error).toHaveBeenCalledWith("执行失败，请重试"));
    expect(warning).not.toHaveBeenCalled();
  });

  it("greys Continue on a review-blocked 409 and focuses the pending reviews", async () => {
    seed(vi.fn());
    const pollOnce = vi.fn().mockResolvedValue(undefined);
    useProjectSnapshotStore.setState({
      pollOnce: pollOnce as unknown as ProjectSnapshotState["pollOnce"],
    });
    const approve = vi.fn().mockRejectedValue(
      new CreatorHttpError(409, {
        message:
          "目标尚未就绪：镜头「开场分镜」还有 2 项审阅待确认，请先在下方审阅卡完成确认，再点「继续」。",
        details: {
          reason: "not_ready",
          blocker: "WAITING_REVIEW",
          blockingReviewIds: ["review-1", "review-2"],
          blockedNodeIds: ["storyboard:r2v-window"],
        },
      }),
    );
    useExecutionAuthorizationStore.setState({ approve });
    render(
      <ExecutionAuthorizationCard
        authorization={makePendingAuthorization({
          targetRef: "element:r2v-window",
          scope: {
            operation: "image_generation",
            workGraph: { nodeId: "storyboard:r2v-window" },
          },
        })}
        project={projectDocument}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() =>
      expect(
        document.querySelector("[data-execution-auth-error]"),
      ).not.toBeNull(),
    );
    expect(
      document.querySelector("[data-execution-auth-error]"),
    ).toHaveTextContent("还有 2 项审阅待确认");
    const blocked = screen.getByRole("button", { name: "需先完成审阅" });
    expect(blocked).toBeDisabled();
    // Blockers are recorded for tray ordering, but focus is only taken when
    // the user explicitly asks to look at them.
    expect(useDecisionFocusStore.getState().reviewIds).toEqual([
      "review-1",
      "review-2",
    ]);
    expect(useDecisionFocusStore.getState().nonce).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "查看待确认项" }));
    expect(useDecisionFocusStore.getState().nonce).toBe(1);
    // The 409 handler polls the snapshot itself, so a bare etag change must
    // not erase the explanation while the blocking reviews still pend.
    act(() =>
      useFileProjectReviewStore.setState({
        projectId: "p1",
        reviews: [
          { review_id: "review-1" },
          { review_id: "review-2" },
        ] as never,
        lastGoodAt: "2026-11-17T00:00:00.000Z",
      }),
    );
    act(() => useProjectSnapshotStore.setState({ etag: "etag-4" }));
    expect(
      document.querySelector("[data-execution-auth-error]"),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "需先完成审阅" })).toBeDisabled();
    // Keeping the reviews removes them from the pending list; the stale block
    // drops and Continue becomes available again without another failed click.
    act(() =>
      useFileProjectReviewStore.setState({
        reviews: [],
        lastGoodAt: "2026-11-17T00:00:05.000Z",
      }),
    );
    expect(document.querySelector("[data-execution-auth-error]")).toBeNull();
    expect(screen.getByRole("button", { name: "继续" })).toBeEnabled();
  });
});
