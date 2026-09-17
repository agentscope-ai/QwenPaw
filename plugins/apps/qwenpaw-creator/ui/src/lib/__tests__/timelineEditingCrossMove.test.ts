/*
 * Regression: dragging a clip across a neighbour (out-of-order transition
 * data) must still resolve to a valid span with the bridging transition
 * following into the new overlap — mirrors the roof-climb restore scenario.
 */
import { describe, expect, it } from "vitest";
import {
  collectSnapTicks,
  resolveSpanDrag,
  transitionFollowChanges,
} from "@/lib/timelineEditing";
import type { TimelineDocument } from "@/contracts/creator";

function el(
  id: string,
  type: string,
  start: number,
  dur: number,
  extra: Record<string, unknown> = {},
) {
  return {
    element_id: id,
    label: id,
    enabled: true,
    span: { start_tick: start, duration_tick: dur },
    location: null,
    z_index: 0,
    creation: { type, ...extra },
    outputs: {},
    render_source: null,
    provenance_refs: [],
  };
}

const xf = (id: string, at: number, from: string, to: string) =>
  el(id, "transition", at, 1000, {
    from_element_id: from,
    to_element_id: to,
    transition_kind: "crossfade",
    easing: "ease-in-out",
  });

const tl = {
  timeline_id: "timeline:main",
  ticks_per_second: 1000,
  elements_by_id: {
    "edit-pond-drink": el("edit-pond-drink", "edit", 11000, 12000),
    "edit-roof-climb": el("edit-roof-climb", "edit", 13570, 12000),
    "edit-cat-face": el("edit-cat-face", "edit", 22000, 10000),
    "edit-riverbed-jump": el("edit-riverbed-jump", "edit", 31000, 10000),
    "edit-railway-explore": el("edit-railway-explore", "edit", 40000, 10000),
    "edit-van-drink": el("edit-van-drink", "edit", 49000, 11000),
    "xf-roof-to-pond": xf(
      "xf-roof-to-pond",
      13570,
      "edit-roof-climb",
      "edit-pond-drink",
    ),
    "xf-pond-to-face": xf(
      "xf-pond-to-face",
      22000,
      "edit-pond-drink",
      "edit-cat-face",
    ),
    "xf-face-to-riverbed": xf(
      "xf-face-to-riverbed",
      31000,
      "edit-cat-face",
      "edit-riverbed-jump",
    ),
    "xf-riverbed-to-railway": xf(
      "xf-riverbed-to-railway",
      40000,
      "edit-riverbed-jump",
      "edit-railway-explore",
    ),
    "xf-railway-to-van": xf(
      "xf-railway-to-van",
      49000,
      "edit-railway-explore",
      "edit-van-drink",
    ),
  },
} as unknown as TimelineDocument;

describe("cross-neighbour move with transition follow", () => {
  it("moves roof back to 0 with xf follow", () => {
    const element = tl.elements_by_id["edit-roof-climb"];
    const snapTicks = collectSnapTicks(
      tl,
      new Set(["edit-roof-climb"]),
      [0, 0, 60000],
    );
    const result = resolveSpanDrag({
      timeline: tl,
      element,
      mode: "move",
      originSpan: element.span,
      deltaTick: -13570,
      snapEnabled: true,
      snapTicks,
      snapThresholdTick: 431,
    });
    // eslint-disable-next-line no-console
    console.log("drag result:", JSON.stringify(result));
    const follow = transitionFollowChanges(tl, [
      { elementId: "edit-roof-climb", span: result.span },
    ]);
    // eslint-disable-next-line no-console
    console.log("follow:", JSON.stringify(follow));
    expect(follow.ok).toBe(true);
  });
});
