import { describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SubtitleSettingsPicker from "../SubtitleSettingsPicker";
import type { SubtitleStyle } from "@/contracts/creator";

function renderPicker(
  overrides: Partial<React.ComponentProps<typeof SubtitleSettingsPicker>> = {},
) {
  const view: React.ComponentProps<typeof SubtitleSettingsPicker> = {
    policy: "off",
    onPolicyChange: vi.fn(),
    template: null,
    onTemplateChange: vi.fn(),
    style: null,
    onStyleChange: vi.fn(),
    ...overrides,
  };
  render(<SubtitleSettingsPicker {...view} />);
  return view;
}

/** A stateful host, so the flows whose window state follows the policy work. */
function Harness() {
  const [policy, setPolicy] = useState("off");
  const [template, setTemplate] = useState<string | null>(null);
  const [style, setStyle] = useState<SubtitleStyle | null>(null);
  return (
    <SubtitleSettingsPicker
      policy={policy}
      onPolicyChange={setPolicy}
      template={template}
      onTemplateChange={setTemplate}
      style={style}
      onStyleChange={setStyle}
    />
  );
}

function openDropdown() {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "字幕" }));
}

async function pickOption(name: string) {
  openDropdown();
  await waitFor(() => expect(screen.getByText(name)).toBeTruthy());
  fireEvent.click(screen.getByText(name).closest(".ant-select-item-option")!);
}

/**
 * A Modal that has been shown keeps its content mounted while it is hidden, so
 * the question is whether the window is on screen, not whether its DOM is.
 */
async function expectWindow(open: boolean) {
  await waitFor(() => {
    const panel = document.querySelector("[data-subtitle-style-modal]");
    if (open) {
      expect(panel).toBeInTheDocument();
      expect(panel).toBeVisible();
    } else if (panel) {
      expect(panel).not.toBeVisible();
    }
  });
}

describe("SubtitleSettingsPicker", () => {
  it("is a dropdown whose pill only reads 字幕, whatever the policy is", () => {
    const { container } = render(
      <SubtitleSettingsPicker
        policy="auto"
        onPolicyChange={vi.fn()}
        template={null}
        onTemplateChange={vi.fn()}
        style={null}
        onStyleChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox", { name: "字幕" })).toBeInTheDocument();
    const label = container.querySelector(".ant-select-content")!.textContent!;
    expect(label).toContain("字幕");
    // The state lives in the dot, never in the wording of the pill.
    expect(label).not.toContain("自动");
    expect(label).not.toContain("关闭");
  });

  it("states each policy's consequence in the dropdown", async () => {
    renderPicker({ policy: "auto" });
    openDropdown();
    await waitFor(() => expect(screen.getByText("自动")).toBeTruthy());
    expect(screen.getByText("根据台词自动生成字幕")).toBeTruthy();
    expect(screen.getByText("关闭")).toBeTruthy();
    expect(screen.getByText("成片中不显示字幕")).toBeTruthy();
  });

  it("opens the style window on 自动 and drops it on 关闭", async () => {
    render(<Harness />);
    await pickOption("自动");
    await expectWindow(true);
    const panel = document.querySelector("[data-subtitle-style-modal]")!;
    expect(panel.textContent).toContain("智能推荐");
    expect(panel.textContent).toContain("综艺花字");
    expect(panel.textContent).toContain("字幕样式");

    await pickOption("关闭");
    await expectWindow(false);
  });

  it("reports the policy the way the dropdown's own values read", async () => {
    const view = renderPicker();
    await pickOption("自动");
    expect(view.onPolicyChange).toHaveBeenCalledWith("auto");
  });

  it("keeps the window reachable while the policy stays auto", async () => {
    render(<Harness />);
    await pickOption("自动");
    await expectWindow(true);

    // antd spaces two CJK characters in a button, hence the optional gap.
    fireEvent.click(screen.getByRole("button", { name: /完\s*成/ }));
    await expectWindow(false);

    // The value does not change the second time, but picking 自动 again is the
    // only way back into the window once it has been closed.
    await pickOption("自动");
    await expectWindow(true);
  });

  it("sizes the window to the viewport instead of a fixed panel", async () => {
    render(<Harness />);
    await pickOption("自动");
    await expectWindow(true);

    const modal = document.querySelector(".ant-modal") as HTMLElement;
    expect(modal.style.maxWidth).toBe("calc(100vw - 32px)");
    const body = document.querySelector(".ant-modal-body") as HTMLElement;
    expect(body.style.overflowY).toBe("auto");
    expect(body.style.maxHeight).toBeTruthy();
  });

  it("carries a pack pick out of the window", async () => {
    const view = renderPicker({ policy: "auto" });
    await pickOption("自动");
    await expectWindow(true);
    fireEvent.click(screen.getByText("综艺花字"));
    expect(view.onTemplateChange).toHaveBeenCalledWith("variety_pop");
  });

  it("carries a motion pick out of the window", async () => {
    const view = renderPicker({
      policy: "auto",
      onAnimationChange: vi.fn(),
    });
    await pickOption("自动");
    await expectWindow(true);
    const panel = document.querySelector("[data-subtitle-style-modal]")!;
    expect(panel.textContent).toContain("字幕动效");
    fireEvent.click(screen.getByRole("button", { name: "滑入" }));
    expect(view.onAnimationChange).toHaveBeenCalledWith({
      entrance: "slide",
    });
  });

  it("takes a motion pick back to the pack default", async () => {
    const view = renderPicker({
      policy: "auto",
      animation: { entrance: "slide" },
      onAnimationChange: vi.fn(),
    });
    await pickOption("自动");
    await expectWindow(true);

    // The lit pill toggles back off, and an emptied policy reads as null.
    fireEvent.click(screen.getByRole("button", { name: "滑入" }));
    expect(view.onAnimationChange).toHaveBeenLastCalledWith(null);

    fireEvent.click(screen.getByRole("button", { name: "恢复默认" }));
    expect(view.onAnimationChange).toHaveBeenLastCalledWith(null);
  });

  it("hides the motion picker when the host cannot persist it", async () => {
    renderPicker({ policy: "auto" });
    await pickOption("自动");
    await expectWindow(true);
    const panel = document.querySelector("[data-subtitle-style-modal]")!;
    expect(panel.textContent).not.toContain("字幕动效");
  });
});
