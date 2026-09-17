import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import SelectionToolbar from "@/components/agent/SelectionToolbar";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";

describe("SelectionToolbar project locator", () => {
  beforeEach(() => {
    useAgentDockUiStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    window.getSelection()?.removeAllRanges();
  });

  it("opens for a Creator field and keeps its semantic locator and exact project.json path", async () => {
    const field = "element:r2v-1/label";
    const path = "/timelines/items/timeline:main/elements_by_id/r2v-1/label";
    const { container } = render(
      <>
        <p
          data-creator-field={field}
          data-creator-path={path}
          data-creator-field-label="VLM 分镜 1 · 描述"
        >
          源视频关键帧
        </p>
        <SelectionToolbar />
      </>,
    );
    const target = container.querySelector("p")!;
    const range = document.createRange();
    range.selectNodeContents(target);
    range.getBoundingClientRect = () => ({
      x: 80,
      y: 80,
      top: 80,
      right: 160,
      bottom: 96,
      left: 80,
      width: 80,
      height: 16,
      toJSON: () => ({}),
    });
    window.getSelection()!.addRange(range);

    fireEvent.mouseUp(target, { clientX: 120, clientY: 80 });
    fireEvent.click(await screen.findByRole("button", { name: "添加到对话" }));

    expect(useAgentDockUiStore.getState().selection).toMatchObject({
      text: "源视频关键帧",
      ref: "element:r2v-1",
      field,
      path,
      label: "VLM 分镜 1 · 描述",
      start: 0,
      end: 6,
    });
    expect(useAgentDockUiStore.getState()).toMatchObject({
      open: true,
      tab: "conversation",
    });
  });
});
