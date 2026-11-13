import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SubtitleAnimationPolicy } from "@/contracts/creator";
import SubtitleAnimationControls from "../SubtitleAnimationControls";

function Harness({
  initial = null,
  allowClear = false,
  onEmit,
}: {
  initial?: SubtitleAnimationPolicy | null;
  allowClear?: boolean;
  onEmit?: (animation: SubtitleAnimationPolicy | null) => void;
}) {
  const [value, setValue] = useState<SubtitleAnimationPolicy | null>(initial);
  return (
    <SubtitleAnimationControls
      value={value}
      allowClear={allowClear}
      onChange={(next) => {
        setValue(next);
        onEmit?.(next);
      }}
    />
  );
}

describe("SubtitleAnimationControls", () => {
  it("offers the renderer's own motion vocabulary", () => {
    render(<Harness />);
    for (const label of ["淡入", "弹入", "滑入", "逐字浮现"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    for (const label of ["缩小", "淡出"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("emits one picked entrance without inventing the other choices", async () => {
    const user = userEvent.setup();
    const emitted: (SubtitleAnimationPolicy | null)[] = [];
    render(<Harness onEmit={(animation) => emitted.push(animation)} />);

    await user.click(screen.getByText("弹入"));

    expect(emitted.at(-1)).toEqual({ entrance: "pop" });
    expect(screen.getByText("弹入")).toHaveAttribute("aria-pressed", "true");
  });

  it("accumulates the triple across picks", async () => {
    const user = userEvent.setup();
    const emitted: (SubtitleAnimationPolicy | null)[] = [];
    render(<Harness onEmit={(animation) => emitted.push(animation)} />);

    await user.click(screen.getByText("滑入"));
    await user.click(screen.getByText("缩小"));
    await user.click(screen.getByText("开"));

    expect(emitted.at(-1)).toEqual({
      entrance: "slide",
      exit: "shrink",
      loop: true,
    });
  });

  it("says the pack decides while nothing is picked", () => {
    render(<Harness />);
    expect(
      screen.getByText("未选择时跟随风格包默认动效"),
    ).toBeInTheDocument();
  });

  it("reflects what the caption document already plays", () => {
    render(<Harness initial={{ entrance: "type_on", exit: "none", loop: false }} />);
    expect(screen.getByText("逐字浮现")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.queryByText("未选择时跟随风格包默认动效"),
    ).not.toBeInTheDocument();
  });

  it("takes a pick back on a second click when clearing is allowed", async () => {
    const user = userEvent.setup();
    const emitted: (SubtitleAnimationPolicy | null)[] = [];
    render(
      <Harness allowClear onEmit={(animation) => emitted.push(animation)} />,
    );

    await user.click(screen.getByText("弹入"));
    expect(emitted.at(-1)).toEqual({ entrance: "pop" });

    await user.click(screen.getByText("弹入"));
    expect(emitted.at(-1)).toBeNull();
    expect(screen.getByText("弹入")).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText("未选择时跟随风格包默认动效"),
    ).toBeInTheDocument();
  });

  it("keeps the other picks when one field is taken back", async () => {
    const user = userEvent.setup();
    const emitted: (SubtitleAnimationPolicy | null)[] = [];
    render(
      <Harness allowClear onEmit={(animation) => emitted.push(animation)} />,
    );

    await user.click(screen.getByText("滑入"));
    await user.click(screen.getByText("缩小"));
    await user.click(screen.getByText("缩小"));

    expect(emitted.at(-1)).toEqual({ entrance: "slide", exit: null });
  });

  it("offers 恢复默认 once a pick exists and it clears the policy", async () => {
    const user = userEvent.setup();
    const emitted: (SubtitleAnimationPolicy | null)[] = [];
    render(
      <Harness
        allowClear
        initial={{ entrance: "pop", loop: true }}
        onEmit={(animation) => emitted.push(animation)}
      />,
    );

    const reset = screen.getByRole("button", { name: "恢复默认" });
    await user.click(reset);

    expect(emitted.at(-1)).toBeNull();
    expect(
      screen.queryByRole("button", { name: "恢复默认" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("弹入")).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps picks sticky where clearing is not offered", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByText("弹入"));
    await user.click(screen.getByText("弹入"));

    expect(screen.getByText("弹入")).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: "恢复默认" }),
    ).not.toBeInTheDocument();
  });
});
