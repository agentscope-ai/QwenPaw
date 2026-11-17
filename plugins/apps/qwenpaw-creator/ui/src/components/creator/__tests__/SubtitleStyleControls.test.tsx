import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SubtitleStyle } from "@/contracts/creator";
import SubtitleStyleControls from "../SubtitleStyleControls";

function Harness({
  onEmit,
}: {
  onEmit?: (style: SubtitleStyle | null) => void;
}) {
  const [value, setValue] = useState<SubtitleStyle | null>(null);
  return (
    <SubtitleStyleControls
      value={value}
      onChange={(next) => {
        setValue(next);
        onEmit?.(next);
      }}
    />
  );
}

describe("SubtitleStyleControls", () => {
  it("starts on every renderer default", () => {
    render(<Harness />);
    expect(screen.getByText("默认")).toHaveAttribute("aria-pressed", "true");
    // 字号与描边各自的标准档
    const standards = screen.getAllByText("标准");
    expect(standards).toHaveLength(2);
    standards.forEach((node) =>
      expect(node).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("emits the chosen colour, size and outline", async () => {
    const user = userEvent.setup();
    const emitted: Array<SubtitleStyle | null> = [];
    render(<Harness onEmit={(style) => emitted.push(style)} />);

    await user.click(screen.getByLabelText("#FFE066"));
    await user.click(screen.getByText("大"));
    await user.click(screen.getByText("无"));

    expect(emitted.at(-1)).toEqual({
      color: "#FFE066",
      fontFamily: null,
      fontScale: 1.25,
      strokeScale: 0,
      backgroundOpacity: null,
    });
  });

  it("keeps the plate opacity beside the other overrides", async () => {
    const user = userEvent.setup();
    const emitted: Array<SubtitleStyle | null> = [];
    render(<Harness onEmit={(style) => emitted.push(style)} />);

    // The row starts on the pack's own alpha, which stores nothing.
    expect(screen.getByText("跟随风格")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByText("无底板"));
    expect(emitted.at(-1)).toEqual({
      color: null,
      fontFamily: null,
      fontScale: null,
      strokeScale: null,
      backgroundOpacity: 0,
    });

    await user.click(screen.getByText("50%"));
    expect(emitted.at(-1)).toMatchObject({ backgroundOpacity: 0.5 });

    // Going back to 跟随风格 clears the only override, so the whole style
    // object collapses and an untouched project still persists no style.
    await user.click(screen.getByText("跟随风格"));
    expect(emitted.at(-1)).toBeNull();
  });

  it("collapses back to null once every override is cleared", async () => {
    const user = userEvent.setup();
    const emitted: Array<SubtitleStyle | null> = [];
    render(<Harness onEmit={(style) => emitted.push(style)} />);

    await user.click(screen.getByLabelText("#7DD3FC"));
    expect(emitted.at(-1)).not.toBeNull();

    await user.click(screen.getByText("默认"));
    expect(emitted.at(-1)).toBeNull();
  });

  it("offers 恢复默认 only while an override is stated, and it clears all", async () => {
    const user = userEvent.setup();
    const emitted: Array<SubtitleStyle | null> = [];
    render(<Harness onEmit={(style) => emitted.push(style)} />);

    // An untouched style has nothing to reset, so the button stays away — the
    // same rule the motion picker's 恢复默认 follows.
    expect(screen.queryByRole("button", { name: "恢复默认" })).toBeNull();

    await user.click(screen.getByLabelText("#FFE066"));
    await user.click(screen.getByRole("button", { name: "恢复默认" }));
    expect(emitted.at(-1)).toBeNull();
    expect(screen.queryByRole("button", { name: "恢复默认" })).toBeNull();
  });

  it("paints each font pill in its own face, the auto one inheriting", () => {
    render(<Harness />);
    expect(
      screen.getByRole("button", { name: "宋体" }).style.fontFamily,
    ).toContain("Songti SC");
    expect(
      screen.getByRole("button", { name: "黑体" }).style.fontFamily,
    ).toContain("PingFang SC");
    expect(
      screen.getByRole("button", { name: "楷体" }).style.fontFamily,
    ).toContain("Kaiti SC");
    expect(
      screen.getByRole("button", { name: "默认字体" }).style.fontFamily,
    ).toBe("");
  });
});
