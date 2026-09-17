import { describe, expect, it } from "vitest";
import { projectDocument } from "@/test/creatorFixtures";
import {
  buildSpanOperations,
  collectSnapTicks,
  minDurationTick,
  resolveSpanDrag,
  snapAdjust,
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

describe("timelineEditing span drags", () => {
  it("clamps move drags at tick zero", () => {
    const timeline = fixtureTimeline();
    const element = timeline.elements_by_id["r2v-window"];
    const result = resolveSpanDrag({
      timeline,
      element,
      mode: "move",
      originSpan: element.span,
      deltaTick: -9999999,
      snapEnabled: false,
      snapTicks: [],
      snapThresholdTick: 0,
    });
    expect(result.span.start_tick).toBe(0);
    expect(result.span.duration_tick).toBe(10000);
  });

  it("snaps a moved block edge onto a neighbour edge", () => {
    const timeline = fixtureTimeline();
    const element = timeline.elements_by_id["overlay-os"];
    const snapTicks = collectSnapTicks(timeline, new Set(["overlay-os"]), [0]);
    // Origin start 6000; drag towards edit-opening's end (8000).
    const result = resolveSpanDrag({
      timeline,
      element,
      mode: "move",
      originSpan: element.span,
      deltaTick: 1940,
      snapEnabled: true,
      snapTicks,
      snapThresholdTick: 120,
    });
    expect(result.span.start_tick).toBe(8000);
    expect(result.snapTick).toBe(8000);
  });

  it("enforces the 0.1s duration floor when trimming", () => {
    const timeline = fixtureTimeline();
    const element = timeline.elements_by_id["overlay-title"];
    const floor = minDurationTick(timeline.ticks_per_second);
    const trimmedEnd = resolveSpanDrag({
      timeline,
      element,
      mode: "trim-end",
      originSpan: element.span,
      deltaTick: -999999,
      snapEnabled: false,
      snapTicks: [],
      snapThresholdTick: 0,
    });
    expect(trimmedEnd.span.duration_tick).toBe(floor);
    const trimmedStart = resolveSpanDrag({
      timeline,
      element,
      mode: "trim-start",
      originSpan: element.span,
      deltaTick: 999999,
      snapEnabled: false,
      snapTicks: [],
      snapThresholdTick: 0,
    });
    expect(trimmedStart.span.duration_tick).toBe(floor);
    expect(trimmedStart.span.start_tick + trimmedStart.span.duration_tick).toBe(
      element.span.start_tick + element.span.duration_tick,
    );
  });

  it("keeps a transition inside its from/to overlap window", () => {
    const timeline = fixtureTimeline();
    const transition = timeline.elements_by_id.transition;
    expect(transitionOverlapWindow(timeline, transition)).toEqual({
      startTick: 5000,
      endTick: 8000,
    });
    const draggedLeft = resolveSpanDrag({
      timeline,
      element: transition,
      mode: "move",
      originSpan: transition.span,
      deltaTick: -99999,
      snapEnabled: false,
      snapTicks: [],
      snapThresholdTick: 0,
    });
    expect(draggedLeft.span.start_tick).toBe(5000);
    const draggedRight = resolveSpanDrag({
      timeline,
      element: transition,
      mode: "move",
      originSpan: transition.span,
      deltaTick: 99999,
      snapEnabled: false,
      snapTicks: [],
      snapThresholdTick: 0,
    });
    expect(draggedRight.span.start_tick + draggedRight.span.duration_tick).toBe(
      8000,
    );
  });

  it("snapAdjust ignores candidates beyond the threshold", () => {
    expect(snapAdjust(105, [100, 300], 10)).toEqual({
      tick: 100,
      snapped: 100,
    });
    expect(snapAdjust(150, [100, 300], 10)).toEqual({
      tick: 150,
      snapped: null,
    });
  });
});

describe("timelineEditing transition follow", () => {
  it("keeps the transition untouched while overlap still covers it", () => {
    const timeline = fixtureTimeline();
    const result = transitionFollowChanges(timeline, [
      {
        elementId: "r2v-window",
        span: { start_tick: 6000, duration_tick: 10000 },
      },
    ]);
    expect(result).toEqual({ ok: true, changes: [] });
  });

  it("shrinks and shifts the transition when overlap tightens", () => {
    const timeline = fixtureTimeline();
    const result = transitionFollowChanges(timeline, [
      {
        elementId: "r2v-window",
        span: { start_tick: 7500, duration_tick: 10000 },
      },
    ]);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.changes).toEqual([
        {
          elementId: "transition",
          span: { start_tick: 7500, duration_tick: 500 },
        },
      ]);
    }
  });

  it("vetoes edits that would break the from/to overlap", () => {
    const timeline = fixtureTimeline();
    const result = transitionFollowChanges(timeline, [
      {
        elementId: "r2v-window",
        span: { start_tick: 9000, duration_tick: 10000 },
      },
    ]);
    expect(result.ok).toBe(false);
    if (result.ok === false) {
      expect(result.reason).toContain("转场");
    }
  });
});

describe("timelineEditing patch building", () => {
  it("emits replace operations only for changed span fields", () => {
    const timeline = fixtureTimeline();
    const operations = buildSpanOperations(timeline, "timeline:main", [
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
  it("lifts resolvable transitions into junctions", () => {
    const timeline = fixtureTimeline();
    const { junctions, orphanTransitionIds } =
      splitTransitionsForDisplay(timeline);
    expect(junctions).toHaveLength(1);
    expect(junctions[0].transition.element_id).toBe("transition");
    expect(junctions[0].centerTick).toBe(7500);
    expect(orphanTransitionIds.size).toBe(0);
  });

  it("keeps dangling transitions as orphans", () => {
    const timeline = fixtureTimeline();
    const transition = timeline.elements_by_id.transition;
    if (transition.creation.type === "transition") {
      transition.creation.to_element_id = "missing-element";
    }
    const { junctions, orphanTransitionIds } =
      splitTransitionsForDisplay(timeline);
    expect(junctions).toHaveLength(0);
    expect(orphanTransitionIds.has("transition")).toBe(true);
  });
});
