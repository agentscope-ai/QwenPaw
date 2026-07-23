import { act, renderHook } from "@testing-library/react";
import type { PointerEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentSummary } from "../../api/types/agents";
import { useAgentLongPress } from "./useAgentLongPress";

const agent: AgentSummary = {
  id: "agent-1",
  name: "Agent One",
  description: "",
  workspace_dir: "",
  enabled: true,
  pinned: false,
};

describe("useAgentLongPress", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires after the long-press threshold", () => {
    vi.useFakeTimers();
    const onLongPress = vi.fn();
    const { result } = renderHook(() => useAgentLongPress(onLongPress));
    const props = result.current.getLongPressProps(agent);

    act(() => {
      props.onPointerDown({
        button: 0,
        pointerId: 7,
        clientX: 10,
        clientY: 10,
        target: document.createElement("div"),
      } as unknown as PointerEvent<HTMLDivElement>);
      vi.advanceTimersByTime(500);
    });

    expect(onLongPress).toHaveBeenCalledOnce();
    expect(onLongPress).toHaveBeenCalledWith(agent);
  });

  it("cancels when the pointer moves beyond the tolerance", () => {
    vi.useFakeTimers();
    const onLongPress = vi.fn();
    const { result } = renderHook(() => useAgentLongPress(onLongPress));
    const props = result.current.getLongPressProps(agent);

    act(() => {
      props.onPointerDown({
        button: 0,
        pointerId: 7,
        clientX: 10,
        clientY: 10,
        target: document.createElement("div"),
      } as unknown as PointerEvent<HTMLDivElement>);
      props.onPointerMove({
        pointerId: 7,
        clientX: 24,
        clientY: 10,
      } as PointerEvent<HTMLDivElement>);
      vi.advanceTimersByTime(500);
    });

    expect(onLongPress).not.toHaveBeenCalled();
  });
});
