import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TimelineTracks from "@/components/timeline/TimelineTracks";
import { projectDocument } from "@/test/creatorFixtures";
import type { ProjectDocument, TimelineDocument } from "@/contracts/creator";
import type { ElementPlaybackStatus } from "@/selectors/elementPlaybackSelectors";

function setup(overrides: Partial<Parameters<typeof TimelineTracks>[0]> = {}) {
  const project = structuredClone(projectDocument) as ProjectDocument;
  const timeline = project.timelines.items["timeline:main"] as TimelineDocument;
  const props = {
    project,
    timeline,
    authorityTimeline: timeline,
    durationTick: 20000,
    playheadTick: 2000,
    zoom: 1,
    snapEnabled: false,
    collapsed: false,
    previewOpen: false,
    editable: true,
    selectedElementId: null as string | null,
    playbackStates: new Map<string, ElementPlaybackStatus>(),
    agentWorking: false,
    onPlayheadChange: vi.fn(),
    onSelectElement: vi.fn(),
    onActiveElementIdsChange: vi.fn(),
    onDragOverridesChange: vi.fn(),
    onCommitSpans: vi.fn(),
    onZoomChange: vi.fn(),
    ...overrides,
  };
  const utils = render(<TimelineTracks {...props} />);
  const chart = utils.container.querySelector(
    "[data-timeline-chart]",
  ) as HTMLDivElement;
  vi.spyOn(chart, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 100,
    left: 0,
    top: 100,
    right: 692,
    bottom: 300,
    width: 692,
    height: 200,
    toJSON: () => ({}),
  });
  return { ...utils, props, chart };
}

describe("TimelineTracks direct manipulation", () => {
  it("renders transitions as junction badges instead of track blocks", () => {
    const { container } = setup();
    expect(
      container.querySelector('[data-transition-junction="transition"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-element-block="transition"]'),
    ).not.toBeInTheDocument();
    // Junction badge sits at the transition center: 7500/20000 = 37.5%.
    const badge = container.querySelector(
      '[data-transition-junction="transition"]',
    ) as HTMLButtonElement;
    expect(badge.style.left).toBe("37.5%");
    // The from clip (edit-opening) and to clip (r2v-window) overlap, so lane
    // packing puts them on rows 0 and 1 (44px each). The badge must sit midway
    // between the two row centers (22px and 66px → 44px) and a dashed link
    // must span the two rows to show the transition connects both elements.
    expect(badge.style.top).toBe("44px");
    const link = container.querySelector(
      '[data-transition-junction-link="transition"]',
    ) as HTMLElement;
    expect(link).toBeInTheDocument();
    expect(link.style.left).toBe("37.5%");
    expect(link.style.top).toBe("22px");
    expect(link.style.height).toBe("44px");
  });

  it("keeps transition-bridged clips on one track row like the reference design", () => {
    const project = structuredClone(projectDocument) as ProjectDocument;
    const timeline = project.timelines.items[
      "timeline:main"
    ] as TimelineDocument;
    // A second clip overlapping edit-opening by 1s, bridged by a crossfade:
    // the overlap is the transition window, so both must stay on one lane.
    timeline.elements_by_id["edit-second"] = {
      ...structuredClone(timeline.elements_by_id["edit-opening"]),
      element_id: "edit-second",
      label: "第二段素材",
      span: { start_tick: 7000, duration_tick: 8000 },
    };
    timeline.elements_by_id["transition-2"] = {
      ...structuredClone(timeline.elements_by_id.transition),
      element_id: "transition-2",
      label: "片段间转场",
      span: { start_tick: 7000, duration_tick: 1000 },
      creation: {
        type: "transition",
        from_element_id: "edit-opening",
        to_element_id: "edit-second",
        transition_kind: "crossfade",
        easing: "ease-in-out",
      },
    };
    const { container } = setup({
      project,
      timeline,
      authorityTimeline: timeline,
    });
    const first = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLElement;
    const second = container.querySelector(
      '[data-element-block="edit-second"]',
    ) as HTMLElement;
    // Same lane row: both blocks share the immediate row container.
    expect(first.parentElement).toBe(second.parentElement);
    // NLE-style butt-joined display: the outgoing clip is drawn up to the cut
    // point (transition center 7500/20000 = 37.5%) and the incoming clip from
    // it, so the blocks never visually stack despite the 1s data overlap.
    expect(first.style.left).toBe("0%");
    expect(first.style.width).toBe("37.5%");
    expect(second.style.left).toBe("37.5%");
    expect(second.style.width).toBe("37.5%");
    // Same-row junction: badge centered on the clip row (rows: ai=0, clip=1
    // → top = 44 + 22 = 66px) and no cross-row link line.
    const badge = container.querySelector(
      '[data-transition-junction="transition-2"]',
    ) as HTMLButtonElement;
    expect(badge.style.top).toBe("66px");
    expect(
      container.querySelector('[data-transition-junction-link="transition-2"]'),
    ).not.toBeInTheDocument();
  });

  it("trims a bridged clip past the cut by shrinking the transition (FCP style)", () => {
    const project = structuredClone(projectDocument) as ProjectDocument;
    const timeline = project.timelines.items[
      "timeline:main"
    ] as TimelineDocument;
    timeline.elements_by_id["edit-second"] = {
      ...structuredClone(timeline.elements_by_id["edit-opening"]),
      element_id: "edit-second",
      label: "第二段素材",
      span: { start_tick: 7000, duration_tick: 8000 },
    };
    timeline.elements_by_id["transition-2"] = {
      ...structuredClone(timeline.elements_by_id.transition),
      element_id: "transition-2",
      label: "片段间转场",
      span: { start_tick: 7000, duration_tick: 1000 },
      creation: {
        type: "transition",
        from_element_id: "edit-opening",
        to_element_id: "edit-second",
        transition_kind: "crossfade",
        easing: "ease-in-out",
      },
    };
    const { container, props } = setup({
      project,
      timeline,
      authorityTimeline: timeline,
      selectedElementId: "edit-opening",
    });
    const handle = container.querySelector(
      '[data-element-block="edit-opening"] [data-element-trim="end"]',
    ) as HTMLElement;
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLButtonElement;
    // Trim the outgoing clip left by 1500 ticks (-45px): real end 8000→6500
    // would sever the transition, so the trim clamps at the minimum overlap
    // (edit-second.start + 100 = 7100) and the transition shrinks into it.
    fireEvent.pointerDown(handle, { button: 0, pointerId: 41, clientX: 300 });
    fireEvent.pointerMove(block, { pointerId: 41, clientX: 255 });
    fireEvent.pointerUp(block, { button: 0, pointerId: 41, clientX: 255 });
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      {
        elementId: "edit-opening",
        span: { start_tick: 0, duration_tick: 7100 },
      },
      // The cross-track fixture transition (edit-opening → r2v-window) also
      // follows back inside the shrunken overlap.
      {
        elementId: "transition",
        span: { start_tick: 6100, duration_tick: 1000 },
      },
      {
        elementId: "transition-2",
        span: { start_tick: 7000, duration_tick: 100 },
      },
    ]);
  });

  it("keeps dangling transitions as ordinary track blocks", () => {
    const project = structuredClone(projectDocument) as ProjectDocument;
    const timeline = project.timelines.items[
      "timeline:main"
    ] as TimelineDocument;
    const transition = timeline.elements_by_id.transition;
    if (transition.creation.type === "transition") {
      transition.creation.to_element_id = "missing";
    }
    const { container } = setup({
      project,
      timeline,
      authorityTimeline: timeline,
    });
    expect(
      container.querySelector('[data-element-block="transition"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector("[data-transition-junction]"),
    ).not.toBeInTheDocument();
  });

  it("selects an element on plain click without committing spans", () => {
    const { container, props } = setup();
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLButtonElement;
    fireEvent.pointerDown(block, { button: 0, pointerId: 3, clientX: 120 });
    fireEvent.pointerUp(block, { button: 0, pointerId: 3, clientX: 121 });
    fireEvent.click(block);
    expect(props.onSelectElement).toHaveBeenCalledWith("edit-opening");
    expect(props.onCommitSpans).not.toHaveBeenCalled();
  });

  it("moves a block and commits the validated span on release", () => {
    const { container, props } = setup();
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLButtonElement;
    // Lane width = 692 - 68 - 24 = 600px for 20000 ticks → 30px = 1000 ticks.
    fireEvent.pointerDown(block, { button: 0, pointerId: 5, clientX: 100 });
    fireEvent.pointerMove(block, { pointerId: 5, clientX: 130 });
    expect(props.onDragOverridesChange).toHaveBeenCalled();
    const overrides = vi
      .mocked(props.onDragOverridesChange)
      .mock.calls.at(-1)?.[0] as Map<
      string,
      { start_tick: number; duration_tick: number }
    >;
    expect(overrides.get("edit-opening")).toEqual({
      start_tick: 1000,
      duration_tick: 8000,
    });
    fireEvent.pointerUp(block, { button: 0, pointerId: 5, clientX: 130 });
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      {
        elementId: "edit-opening",
        span: { start_tick: 1000, duration_tick: 8000 },
      },
    ]);
    // The click fired after a drag must not change the selection.
    fireEvent.click(block);
    expect(props.onSelectElement).not.toHaveBeenCalled();
  });

  it("trims from the end via the trim handle", () => {
    const { container, props } = setup({ selectedElementId: "edit-opening" });
    const handle = container.querySelector(
      '[data-element-block="edit-opening"] [data-element-trim="end"]',
    ) as HTMLElement;
    expect(handle).toBeInTheDocument();
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLButtonElement;
    fireEvent.pointerDown(handle, {
      button: 0,
      pointerId: 6,
      clientX: 300,
    });
    fireEvent.pointerMove(block, { pointerId: 6, clientX: 270 });
    fireEvent.pointerUp(block, { button: 0, pointerId: 6, clientX: 270 });
    // Trimming the from-clip to 7000 shrinks the transition overlap window to
    // [5000,7000]; the transition auto-follows into the new junction.
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      {
        elementId: "edit-opening",
        span: { start_tick: 0, duration_tick: 7000 },
      },
      {
        elementId: "transition",
        span: { start_tick: 6000, duration_tick: 1000 },
      },
    ]);
  });

  it("clamps a move so an attached transition keeps its minimum overlap", () => {
    const { container, props } = setup();
    const block = container.querySelector(
      '[data-element-block="r2v-window"]',
    ) as HTMLButtonElement;
    // r2v-window starts at 5000; +150px = +5000 ticks would leave the
    // transition without overlap. FCP-style trimming clamps the move at the
    // last position that preserves the minimum 0.1s overlap (7900) and the
    // transition shrinks into it instead of vetoing the gesture.
    fireEvent.pointerDown(block, { button: 0, pointerId: 7, clientX: 200 });
    fireEvent.pointerMove(block, { pointerId: 7, clientX: 350 });
    fireEvent.pointerUp(block, { button: 0, pointerId: 7, clientX: 350 });
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      {
        elementId: "r2v-window",
        span: { start_tick: 7900, duration_tick: 10000 },
      },
      {
        elementId: "transition",
        span: { start_tick: 7900, duration_tick: 100 },
      },
    ]);
  });

  it("starts a range selection with shift+drag even on top of blocks", () => {
    const { container, chart, props } = setup();
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLButtonElement;
    // Shift+drag from a block into the timeline must select a range instead
    // of moving the clip: no overrides, no commit, toolbar appears.
    fireEvent.pointerDown(block, {
      button: 0,
      pointerId: 31,
      clientX: 110,
      shiftKey: true,
    });
    fireEvent.pointerDown(chart, {
      button: 0,
      pointerId: 31,
      clientX: 110,
      shiftKey: true,
    });
    fireEvent.pointerMove(chart, {
      pointerId: 31,
      clientX: 290,
      shiftKey: true,
    });
    fireEvent.pointerUp(chart, {
      button: 0,
      pointerId: 31,
      clientX: 290,
      shiftKey: true,
    });
    expect(props.onDragOverridesChange).not.toHaveBeenCalled();
    expect(props.onCommitSpans).not.toHaveBeenCalled();
    expect(
      container.querySelector("[data-timeline-selection-range]"),
    ).toBeInTheDocument();
    expect(
      document.querySelector("[data-timeline-selection-toolbar]"),
    ).toBeInTheDocument();
    expect(props.onActiveElementIdsChange).toHaveBeenCalledWith([
      "edit-opening",
      "audio-bgm",
      "overlay-title",
      "r2v-window",
      "overlay-os",
    ]);
  });

  it("scrubs the playhead by press-dragging the ruler", () => {
    const { container, props } = setup();
    const ruler = container.querySelector(
      "[data-timeline-scale]",
    ) as HTMLDivElement;
    // Lane width 600px for 20000 ticks; x offsets include 12px padding + 68px
    // labels → clientX 380 ≈ tick 10000, clientX 230 ≈ tick 5000.
    fireEvent.pointerDown(ruler, { button: 0, pointerId: 21, clientX: 380 });
    fireEvent.pointerMove(ruler, { pointerId: 21, clientX: 230 });
    fireEvent.pointerUp(ruler, { button: 0, pointerId: 21, clientX: 230 });
    expect(
      vi.mocked(props.onPlayheadChange).mock.calls.map(([tick]) => tick),
    ).toEqual([10000, 5000]);
    // Scrubbing must not open the range-selection toolbar.
    expect(
      document.querySelector("[data-timeline-selection-toolbar]"),
    ).not.toBeInTheDocument();
  });

  it("zooms around the pointer with ctrl+wheel", () => {
    const { container, props } = setup();
    const chart = container.querySelector(
      "[data-timeline-chart]",
    ) as HTMLDivElement;
    fireEvent.wheel(chart, { ctrlKey: true, deltaY: -120, clientX: 380 });
    expect(props.onZoomChange).toHaveBeenCalledWith(1.25);
    fireEvent.wheel(chart, { ctrlKey: true, deltaY: 120, clientX: 380 });
    expect(props.onZoomChange).toHaveBeenCalledWith(0.75);
    // Plain wheel without the modifier must not zoom.
    vi.mocked(props.onZoomChange).mockClear();
    fireEvent.wheel(chart, { deltaY: -120, clientX: 380 });
    expect(props.onZoomChange).not.toHaveBeenCalled();
  });

  it("shows a time tip chip while dragging a block", () => {
    const { container } = setup();
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLButtonElement;
    fireEvent.pointerDown(block, { button: 0, pointerId: 22, clientX: 100 });
    fireEvent.pointerMove(block, { pointerId: 22, clientX: 130 });
    const tip = container.querySelector("[data-timeline-drag-tip]");
    expect(tip).toHaveTextContent("1s – 9s · 8s");
    fireEvent.pointerUp(block, { button: 0, pointerId: 22, clientX: 130 });
    expect(
      container.querySelector("[data-timeline-drag-tip]"),
    ).not.toBeInTheDocument();
  });

  it("drags the junction badge within the from/to overlap window", () => {
    const { container, props } = setup();
    const badge = container.querySelector(
      '[data-transition-junction="transition"]',
    ) as HTMLButtonElement;
    // Transition [7000,8000] inside window [5000,8000]; dragging right is
    // clamped so the span cannot leave the overlap.
    fireEvent.pointerDown(badge, { button: 0, pointerId: 8, clientX: 400 });
    fireEvent.pointerMove(badge, { pointerId: 8, clientX: 520 });
    fireEvent.pointerUp(badge, { button: 0, pointerId: 8, clientX: 520 });
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      {
        elementId: "transition",
        span: { start_tick: 7000, duration_tick: 1000 },
      },
    ]);
  });
});
