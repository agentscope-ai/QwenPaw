import { describe, expect, it } from "vitest";
import { projectDocument } from "@/test/creatorFixtures";
import {
  buildSpanOperations,
  collectSnapTicks,
  minDurationTick,
  resolveSpanDrag,
  splitTransitionsForDisplay,
  transitionFollowChanges,
  transitionOverlapWindow,
} from "@/lib/timelineEditing";
import type { TimelineDocument } from "@/contracts/creator";

function fixtureTimeline(): TimelineDocument {
  return structuredClone(
    projectDocument.timelines.items["timeline:main"],
  ) as TimelineDocument;
}

function drag(
  timeline: TimelineDocument,
  elementId: string,
  mode: "move" | "trim-start" | "trim-end",
  deltaTick: number,
  snap?: { snapTicks: number[]; snapThresholdTick: number },
) {
  const element = timeline.elements_by_id[elementId];
  return resolveSpanDrag({
    timeline,
    element,
    mode,
    originSpan: element.span,
    deltaTick,
    snapEnabled: Boolean(snap),
    snapTicks: snap?.snapTicks ?? [],
    snapThresholdTick: snap?.snapThresholdTick ?? 0,
  });
}

describe("timelineEditing span drags", () => {
  it("clamps move drags at tick zero and enforces the 0.1s duration floor", () => {
    const moved = drag(fixtureTimeline(), "r2v-window", "move", -9999999);
    expect(moved.span.start_tick).toBe(0);
    expect(moved.span.duration_tick).toBe(10000);

    const timeline = fixtureTimeline();
    const element = timeline.elements_by_id["overlay-title"];
    const floor = minDurationTick(timeline.ticks_per_second);
    const trimmedEnd = drag(timeline, "overlay-title", "trim-end", -999999);
    expect(trimmedEnd.span.duration_tick).toBe(floor);
    const trimmedStart = drag(timeline, "overlay-title", "trim-start", 999999);
    expect(trimmedStart.span.duration_tick).toBe(floor);
    expect(trimmedStart.span.start_tick + trimmedStart.span.duration_tick).toBe(
      element.span.start_tick + element.span.duration_tick,
    );
  });

  it("snaps a moved block edge onto a neighbour edge", () => {
    const timeline = fixtureTimeline();
    const snapTicks = collectSnapTicks(timeline, new Set(["overlay-os"]), [0]);
    // Origin start 6000; drag towards edit-opening's end (8000).
    const result = drag(timeline, "overlay-os", "move", 1940, {
      snapTicks,
      snapThresholdTick: 120,
    });
    expect(result.span.start_tick).toBe(8000);
    expect(result.snapTick).toBe(8000);
  });

  it("keeps a transition inside its from/to overlap window", () => {
    const timeline = fixtureTimeline();
    expect(
      transitionOverlapWindow(timeline, timeline.elements_by_id.transition),
    ).toEqual({ startTick: 5000, endTick: 8000 });
    const draggedLeft = drag(timeline, "transition", "move", -99999);
    expect(draggedLeft.span.start_tick).toBe(5000);
    const draggedRight = drag(timeline, "transition", "move", 99999);
    expect(draggedRight.span.start_tick + draggedRight.span.duration_tick).toBe(
      8000,
    );
  });
});

describe("timelineEditing transition follow", () => {
  const follow = (start_tick: number) =>
    transitionFollowChanges(fixtureTimeline(), [
      { elementId: "r2v-window", span: { start_tick, duration_tick: 10000 } },
    ]);

  it("keeps, shrinks or vetoes the transition as overlap changes", () => {
    expect(follow(6000)).toEqual({ ok: true, changes: [] });

    const shrunk = follow(7500);
    expect(shrunk.ok).toBe(true);
    if (shrunk.ok) {
      expect(shrunk.changes).toEqual([
        {
          elementId: "transition",
          span: { start_tick: 7500, duration_tick: 500 },
        },
      ]);
    }

    const vetoed = follow(9000);
    expect(vetoed.ok).toBe(false);
    if (vetoed.ok === false) {
      expect(vetoed.reason).toContain("转场");
    }
  });
});

describe("timelineEditing patch building", () => {
  it("emits replace operations only for changed span fields", () => {
    const operations = buildSpanOperations(fixtureTimeline(), "timeline:main", [
      {
        elementId: "edit-opening",
        span: { start_tick: 1000, duration_tick: 8000 },
      },
    ]);
    expect(operations).toEqual([
      {
        op: "replace",
        path: "/timelines/items/timeline:main/elements_by_id/edit-opening/span/start_tick",
        before: 0,
        value: 1000,
      },
    ]);
  });
});

describe("timelineEditing transition display split", () => {
  it("lifts resolvable transitions into junctions and keeps dangling ones as orphans", () => {
    const resolved = splitTransitionsForDisplay(fixtureTimeline());
    expect(resolved.junctions).toHaveLength(1);
    expect(resolved.junctions[0].transition.element_id).toBe("transition");
    expect(resolved.junctions[0].centerTick).toBe(7500);
    expect(resolved.orphanTransitionIds.size).toBe(0);

    const timeline = fixtureTimeline();
    const transition = timeline.elements_by_id.transition;
    if (transition.creation.type === "transition") {
      transition.creation.to_element_id = "missing-element";
    }
    const dangling = splitTransitionsForDisplay(timeline);
    expect(dangling.junctions).toHaveLength(0);
    expect(dangling.orphanTransitionIds.has("transition")).toBe(true);
  });
});

/*
 * Regression: dragging a clip across a neighbour (out-of-order transition
 * data) must still resolve to a valid span with the bridging transition
 * following into the new overlap — mirrors the roof-climb restore scenario.
 */
function el(
  id: string,
  type: string,
  start: number,
  dur: number,
  extra: Record<string, unknown> = {},
) {
  return {
    element_id: id,
    enabled: true,
    span: { start_tick: start, duration_tick: dur },
    z_index: 0,
    creation: { type, ...extra },
    outputs: {},
    render_source: null,
  };
}

const xf = (id: string, at: number, from: string, to: string) =>
  el(id, "transition", at, 1000, {
    from_element_id: from,
    to_element_id: to,
    transition_kind: "crossfade",
    easing: "ease-in-out",
  });

const chain: Array<[string, number, string, string]> = [
  ["xf1", 13570, "edit-roof-climb", "edit-pond-drink"],
  ["xf2", 22000, "edit-pond-drink", "edit-cat-face"],
];

const tl = {
  timeline_id: "timeline:main",
  ticks_per_second: 1000,
  elements_by_id: {
    "edit-pond-drink": el("edit-pond-drink", "edit", 11000, 12000),
    "edit-roof-climb": el("edit-roof-climb", "edit", 13570, 12000),
    "edit-cat-face": el("edit-cat-face", "edit", 22000, 10000),
    ...Object.fromEntries(
      chain.map(([id, at, from, to]) => [id, xf(id, at, from, to)]),
    ),
  },
} as unknown as TimelineDocument;

describe("cross-neighbour move with transition follow", () => {
  it("moves roof back to 0 with xf follow", () => {
    const snapTicks = collectSnapTicks(
      tl,
      new Set(["edit-roof-climb"]),
      [0, 0, 60000],
    );
    const result = drag(tl, "edit-roof-climb", "move", -13570, {
      snapTicks,
      snapThresholdTick: 431,
    });
    const follow = transitionFollowChanges(tl, [
      { elementId: "edit-roof-climb", span: result.span },
    ]);
    expect(follow.ok).toBe(true);
  });
});
