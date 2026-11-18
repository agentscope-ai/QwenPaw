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

  it("shows the snapshot conflict and refreshes instead of a generic failure", async () => {
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
      expect(warning).toHaveBeenCalledWith(
        "已保存的项目快照已改变，请重新保存后批准",
      ),
    );
    expect(pollOnce).toHaveBeenCalledWith("p1");
    expect(error).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    await waitFor(() => expect(error).toHaveBeenCalledWith("执行失败，请重试"));
    expect(warning).toHaveBeenCalledTimes(1);
  });
});
