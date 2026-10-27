import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentProgressOverview from "@/components/agent/AgentProgressOverview";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";

function rect(height: number): DOMRect {
  return {
    height,
    width: 300,
    top: 0,
    left: 0,
    bottom: height,
    right: 300,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
}

describe("creation overview drag-to-resize", () => {
  beforeEach(() => {
    useAgentDockUiStore.getState().reset();
  });

  it("drags within [floor, feed slack], nudges by keyboard, survives collapse and resets on double click", () => {
    const { container } = render(
      <div data-agent-dock>
        <AgentProgressOverview projectId="p1" />
        <div data-feed style={{ flexGrow: 1 }} />
      </div>,
    );
    const dock = container.querySelector<HTMLElement>("[data-agent-dock]")!;
    const section = container.querySelector<HTMLElement>(
      "[data-agent-progress-overview]",
    )!;
    Object.defineProperty(dock, "clientHeight", { value: 600 });
    vi.spyOn(section, "getBoundingClientRect").mockReturnValue(rect(160));
    vi.spyOn(
      container.querySelector<HTMLElement>("[data-feed]")!,
      "getBoundingClientRect",
    ).mockReturnValue(rect(300));
    const handle = () =>
      container.querySelector<HTMLElement>("[data-agent-overview-resize]");
    const header = () =>
      section.querySelector<HTMLButtonElement>(".agent-progress-header")!;
    const stored = () => useAgentDockUiStore.getState().overviewHeight;

    expect(section).not.toHaveAttribute("data-resized");
    expect(handle()).toHaveAttribute("role", "separator");

    fireEvent.pointerDown(handle()!, { button: 0, clientY: 100 });
    fireEvent.pointerMove(window, { clientY: 180 });
    expect(stored()).toBe(240);
    expect(section).toHaveAttribute("data-resized", "true");
    expect(section.getAttribute("style")).toContain(
      "--agent-overview-height: 240px",
    );
    fireEvent.pointerMove(window, { clientY: -500 });
    expect(stored()).toBe(96);
    // 160 (current) + 300 (feed slack) - 120 (feed floor)
    fireEvent.pointerMove(window, { clientY: 900 });
    expect(stored()).toBe(340);
    fireEvent.pointerUp(window);
    fireEvent.pointerMove(window, { clientY: 400 });
    expect(stored()).toBe(340);

    fireEvent.keyDown(handle()!, { key: "ArrowDown" });
    expect(stored()).toBe(176);
    fireEvent.keyDown(handle()!, { key: "ArrowUp" });
    expect(stored()).toBe(144);

    fireEvent.click(header());
    expect(section).toHaveAttribute("data-expanded", "false");
    expect(section).not.toHaveAttribute("data-resized");
    expect(handle()).toBeNull();
    expect(stored()).toBe(144);
    fireEvent.click(header());
    expect(section).toHaveAttribute("data-resized", "true");

    fireEvent.doubleClick(handle()!);
    expect(stored()).toBeNull();
    expect(section).not.toHaveAttribute("data-resized");
  });
});
