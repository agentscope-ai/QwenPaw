import { createRef } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PromptEditorModal from "../PromptEditorModal";
import PromptTokenEditor, {
  type PromptTokenEditorHandle,
} from "../PromptTokenEditor";
import PromptRichBlock, { type PromptRichToken } from "../PromptRichBlock";

const token: PromptRichToken = {
  index: 1,
  name: "噜噜角色图",
  thumbUrl: "/test-lulu.png",
  kind: "artifact",
  referenceId: "lulu-v1",
};

describe("prompt image interactions", () => {
  it("previews without changing the prompt and removes only the citation whose close button was clicked", () => {
    const ref = createRef<PromptTokenEditorHandle>();
    const onChange = vi.fn();
    const onPreview = vi.fn();
    const initialValue = "起始 [Image 1] 中间 [Image 1] 结尾 [Image 9]";
    render(
      <PromptTokenEditor
        ref={ref}
        initialValue={initialValue}
        tokens={[token]}
        onChange={onChange}
        onPreview={onPreview}
      />,
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "查看引用图片：噜噜角色图" })[0],
    );
    expect(onPreview).toHaveBeenCalledWith(token);
    expect(onChange).not.toHaveBeenCalled();
    expect(ref.current?.getValue()).toBe(initialValue);

    fireEvent.click(
      screen.getAllByRole("button", { name: "移除引用：噜噜角色图" })[0],
    );
    expect(ref.current?.getValue()).toBe("起始  中间 [Image 1] 结尾 [Image 9]");
    expect(onPreview).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("⚠ IMG 9 未绑定"));
    expect(ref.current?.getValue()).toContain("[Image 9]");
    fireEvent.click(screen.getByRole("button", { name: "移除引用：IMG 9" }));
    expect(ref.current?.getValue()).toBe("起始  中间 [Image 1] 结尾 ");
  });

  it("keeps preview available while a disabled editor cannot remove or insert a citation", () => {
    const ref = createRef<PromptTokenEditorHandle>();
    const onChange = vi.fn();
    const onPreview = vi.fn();
    render(
      <PromptTokenEditor
        ref={ref}
        initialValue="[Image 1]"
        tokens={[token]}
        disabled
        onChange={onChange}
        onPreview={onPreview}
      />,
    );
    const remove = screen.getByRole("button", { name: "移除引用：噜噜角色图" });
    expect(remove).toBeDisabled();
    fireEvent.click(remove);
    ref.current?.insertToken(1);
    expect(ref.current?.getValue()).toBe("[Image 1]");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "查看引用图片：噜噜角色图" }),
    );
    expect(onPreview).toHaveBeenCalledWith(token);
  });

  it("previews the sidebar thumbnail without inserting, then inserts from its name at the saved caret", async () => {
    const onDone = vi.fn();
    const onCancel = vi.fn();
    render(
      <PromptEditorModal
        open
        label="视频提示词"
        initialValue="前后"
        tokens={[token]}
        onCancel={onCancel}
        onDone={onDone}
      />,
    );
    const editor = screen.getByRole("textbox");
    editor.focus();
    const range = document.createRange();
    range.setStart(editor.firstChild!, 1);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.mouseUp(editor);

    const row = document.querySelector(
      "[data-prompt-reference-row='1']",
    ) as HTMLElement;
    fireEvent.click(
      within(row).getByRole("button", { name: "查看引用图片：噜噜角色图" }),
    );
    await waitFor(() =>
      expect(document.querySelector(".ant-image-preview-img")).toHaveAttribute(
        "src",
        "/test-lulu.png",
      ),
    );
    expect(editor.querySelectorAll("[data-image-index]")).toHaveLength(0);
    expect(editor.textContent).toBe("前后");
    const close = document.querySelector(
      ".ant-image-preview-close",
    ) as HTMLElement;
    fireEvent.click(close);
    await waitFor(() =>
      expect(
        document.querySelector(".ant-image-preview-img"),
      ).not.toBeInTheDocument(),
    );
    expect(onCancel).not.toHaveBeenCalled();

    fireEvent.click(
      within(row).getByRole("button", { name: "插入引用：噜噜角色图" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "完 成" }));
    expect(onDone).toHaveBeenCalledWith("前[Image 1] 后", []);
  });

  it("gates editing and regeneration until the agent writes the prompt", () => {
    const props = {
      label: "视频提示词",
      onChange: vi.fn(),
      field: "video_prompt",
      path: "/episodes/0/video_prompt",
      tokens: [] as PromptRichToken[],
      onRegenerate: vi.fn(),
      regenerateLabel: "再次生成视频",
    };
    const { rerender } = render(<PromptRichBlock {...props} value="" />);
    expect(screen.getByText("等待 Agent 编写生成提示词")).toBeInTheDocument();
    expect(document.querySelector("[data-prompt-edit]")).toBeDisabled();
    expect(document.querySelector("[data-prompt-regenerate]")).toBeDisabled();

    rerender(<PromptRichBlock {...props} value="一段写好的提示词" />);
    expect(document.querySelector("[data-prompt-edit]")).toBeEnabled();
    expect(document.querySelector("[data-prompt-regenerate]")).toBeEnabled();

    // Clearing a written prompt is an edit in progress, not a hand-back to
    // the agent: the editor must stay usable or the user is locked out.
    rerender(<PromptRichBlock {...props} value="" />);
    expect(
      screen.queryByText("等待 Agent 编写生成提示词"),
    ).not.toBeInTheDocument();
    expect(document.querySelector("[data-prompt-edit]")).toBeEnabled();
    expect(document.querySelector("[data-prompt-regenerate]")).toBeEnabled();
  });
});
