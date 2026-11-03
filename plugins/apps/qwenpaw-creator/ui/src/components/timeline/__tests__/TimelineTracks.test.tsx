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
    authorityTimeline: overrides.timeline ?? timeline,
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
    left: 0,
    top: 100,
    right: 692,
    bottom: 300,
    width: 692,
    height: 200,
  } as DOMRect);
  return { ...utils, props, chart };
}

function query(root: ParentNode, selector: string) {
  return root.querySelector(selector) as HTMLElement;
}

/** Full pointer down → move → up gesture with a shared pointer id. */
function drag(
  down: Element,
  move: Element,
  pointerId: number,
  fromX: number,
  toX: number,
  extra: Record<string, unknown> = {},
) {
  fireEvent.pointerDown(down, {
    button: 0,
    pointerId,
    clientX: fromX,
    ...extra,
  });
  fireEvent.pointerMove(move, { pointerId, clientX: toX, ...extra });
  fireEvent.pointerUp(move, { button: 0, pointerId, clientX: toX, ...extra });
}

const committed = (elementId: string, start: number, duration: number) => ({
  elementId,
  span: { start_tick: start, duration_tick: duration },
});

/** Second clip overlapping edit-opening by 1s, bridged by a crossfade. */
function withBridgedSecondClip() {
  const project = structuredClone(projectDocument) as ProjectDocument;
  const timeline = project.timelines.items["timeline:main"] as TimelineDocument;
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
  return { project, timeline };
}

describe("TimelineTracks direct manipulation", () => {
  it("renders transitions as junction badges instead of track blocks", () => {
    const { container } = setup();
    expect(
      container.querySelector('[data-element-block="transition"]'),
    ).not.toBeInTheDocument();
    // Junction badge sits at the transition center: 7500/20000 = 37.5%.
    const badge = query(container, '[data-transition-junction="transition"]');
    expect(badge.style.left).toBe("37.5%");
  });

  it("trims a bridged clip past the cut by shrinking the transition (FCP style)", () => {
    const { container, props } = setup({
      ...withBridgedSecondClip(),
      selectedElementId: "edit-opening",
    });
    const handle = query(
      container,
      '[data-element-block="edit-opening"] [data-element-trim="end"]',
    );
    const block = query(container, '[data-element-block="edit-opening"]');
    // Trim the outgoing clip left by 1500 ticks (-45px): real end 8000→6500
    // would sever the transition, so the trim clamps at the minimum overlap
    // (edit-second.start + 100 = 7100) and the transition shrinks into it.
    fireEvent.pointerDown(handle, { button: 0, pointerId: 41, clientX: 300 });
    fireEvent.pointerMove(block, { pointerId: 41, clientX: 255 });
    fireEvent.pointerUp(block, { button: 0, pointerId: 41, clientX: 255 });
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      committed("edit-opening", 0, 7100),
      // The cross-track fixture transition (edit-opening → r2v-window) also
      // follows back inside the shrunken overlap.
      committed("transition", 6100, 1000),
      committed("transition-2", 7000, 100),
    ]);
  });

  it("selects an element on plain click without committing spans", () => {
    const { container, props } = setup();
    const block = query(container, '[data-element-block="edit-opening"]');
    fireEvent.pointerDown(block, { button: 0, pointerId: 3, clientX: 120 });
    fireEvent.pointerUp(block, { button: 0, pointerId: 3, clientX: 121 });
    fireEvent.click(block);
    expect(props.onSelectElement).toHaveBeenCalledWith("edit-opening");
    expect(props.onCommitSpans).not.toHaveBeenCalled();
  });

  it("moves a block with a live drag tip and commits the validated span", () => {
    const { container, props } = setup();
    const block = query(container, '[data-element-block="edit-opening"]');
    // Lane width = 692 - 68 - 24 = 600px for 20000 ticks → 30px = 1000 ticks.
    fireEvent.pointerDown(block, { button: 0, pointerId: 5, clientX: 100 });
    fireEvent.pointerMove(block, { pointerId: 5, clientX: 130 });
    const overrides = vi
      .mocked(props.onDragOverridesChange)
      .mock.calls.at(-1)?.[0] as Map<string, unknown>;
    expect(overrides.get("edit-opening")).toEqual({
      start_tick: 1000,
      duration_tick: 8000,
    });
    // A time tip chip follows the gesture and disappears on release.
    expect(query(container, "[data-timeline-drag-tip]")).toHaveTextContent(
      "1s – 9s · 8s",
    );
    fireEvent.pointerUp(block, { button: 0, pointerId: 5, clientX: 130 });
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      committed("edit-opening", 1000, 8000),
    ]);
    expect(container.querySelector("[data-timeline-drag-tip]")).toBeNull();
    // The click fired after a drag must not change the selection.
    fireEvent.click(block);
    expect(props.onSelectElement).not.toHaveBeenCalled();
  });

  it("clamps a move so an attached transition keeps its minimum overlap", () => {
    const { container, props } = setup();
    const block = query(container, '[data-element-block="r2v-window"]');
    // +150px = +5000 ticks would leave no overlap: the move clamps at the
    // minimum 0.1s overlap and the transition shrinks instead of vetoing.
    drag(block, block, 7, 200, 350);
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      committed("r2v-window", 7900, 10000),
      committed("transition", 7900, 100),
    ]);
  });

  it("starts a range selection with shift+drag even on top of blocks", () => {
    const { container, chart, props } = setup();
    const block = query(container, '[data-element-block="edit-opening"]');
    // Shift+drag on a block selects a range: no overrides/commit, toolbar on.
    fireEvent.pointerDown(block, {
      button: 0,
      pointerId: 31,
      clientX: 110,
      shiftKey: true,
    });
    drag(chart, chart, 31, 110, 290, { shiftKey: true });
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
    const ruler = query(container, "[data-timeline-scale]");
    // Lane width 600px for 20000 ticks; x includes 12px padding + 68px labels
    // → clientX 380 ≈ tick 10000, clientX 230 ≈ tick 5000.
    drag(ruler, ruler, 21, 380, 230);
    expect(
      vi.mocked(props.onPlayheadChange).mock.calls.map(([tick]) => tick),
    ).toEqual([10000, 5000]);
    // Scrubbing must not open the range-selection toolbar.
    expect(
      document.querySelector("[data-timeline-selection-toolbar]"),
    ).not.toBeInTheDocument();
  });

  it("drags the junction badge within the from/to overlap window", () => {
    const { container, props } = setup();
    const badge = query(container, '[data-transition-junction="transition"]');
    // Transition [7000,8000] inside window [5000,8000]; dragging right is
    // clamped so the span cannot leave the overlap.
    drag(badge, badge, 8, 400, 520);
    expect(props.onCommitSpans).toHaveBeenCalledWith([
      committed("transition", 7000, 1000),
    ]);
  });
});
