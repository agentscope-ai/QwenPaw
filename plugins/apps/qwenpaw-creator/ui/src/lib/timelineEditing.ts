import type {
  TimelineDocument,
  TimelineElementDocument,
  TimelineSpanDocument,
} from "@/contracts/creator";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import i18n from "@/i18n";

export type SpanDragMode = "move" | "trim-start" | "trim-end";

export interface SpanChange {
  elementId: string;
  span: TimelineSpanDocument;
}

export interface SpanDragResult {
  span: TimelineSpanDocument;
  snapTick: number | null;
}

export type TransitionFollowResult =
  | { ok: true; changes: SpanChange[] }
  | { ok: false; reason: string };

/** Spans shorter than 0.1s are almost always accidental trims. */
export function minDurationTick(ticksPerSecond: number): number {
  return Math.max(1, Math.round(ticksPerSecond / 10));
}

function spanOf(
  timeline: TimelineDocument,
  elementId: string,
  overrides?: Map<string, TimelineSpanDocument>,
): TimelineSpanDocument | null {
  const override = overrides?.get(elementId);
  if (override) return override;
  return timeline.elements_by_id[elementId]?.span ?? null;
}

/** Blend window available to a transition: the time overlap of its from/to elements. */
export function transitionOverlapWindow(
  timeline: TimelineDocument,
  transition: TimelineElementDocument,
  overrides?: Map<string, TimelineSpanDocument>,
): { startTick: number; endTick: number } | null {
  if (transition.creation.type !== "transition") return null;
  const from = spanOf(timeline, transition.creation.from_element_id, overrides);
  const to = spanOf(timeline, transition.creation.to_element_id, overrides);
  if (!from || !to) return null;
  const startTick = Math.max(from.start_tick, to.start_tick);
  const endTick = Math.min(
    from.start_tick + from.duration_tick,
    to.start_tick + to.duration_tick,
  );
  return endTick > startTick ? { startTick, endTick } : null;
}

/** Snap candidates: other elements' edges plus explicit extra ticks (playhead, 0…). */
export function collectSnapTicks(
  timeline: TimelineDocument,
  excludeIds: Set<string>,
  extraTicks: number[] = [],
): number[] {
  const ticks = new Set<number>(
    extraTicks.filter((tick) => Number.isFinite(tick) && tick >= 0),
  );
  Object.values(timeline.elements_by_id).forEach((element) => {
    if (!element.enabled || excludeIds.has(element.element_id)) return;
    ticks.add(element.span.start_tick);
    ticks.add(element.span.start_tick + element.span.duration_tick);
  });
  return [...ticks];
}

export function snapAdjust(
  tick: number,
  snapTicks: number[],
  thresholdTick: number,
): { tick: number; snapped: number | null } {
  let best: number | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const candidate of snapTicks) {
    const distance = Math.abs(candidate - tick);
    if (distance < bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
  }
  if (best !== null && bestDistance <= thresholdTick) {
    return { tick: best, snapped: best };
  }
  return { tick, snapped: null };
}

/**
 * FCP-style trim bounds from attached transitions: dragging never severs a
 * transition — the span is clamped so at least the minimum transition overlap
 * remains with each bridged partner, and the transition shrinks to fit.
 */
function transitionPartnerBounds(
  timeline: TimelineDocument,
  element: TimelineElementDocument,
): { minEndTick: number; maxStartTick: number } {
  const minTick = minDurationTick(timeline.ticks_per_second);
  let minEndTick = Number.NEGATIVE_INFINITY;
  let maxStartTick = Number.POSITIVE_INFINITY;
  for (const candidate of Object.values(timeline.elements_by_id)) {
    if (candidate.creation.type !== "transition" || !candidate.enabled)
      continue;
    if (candidate.creation.from_element_id === element.element_id) {
      const to = timeline.elements_by_id[candidate.creation.to_element_id];
      if (to) {
        minEndTick = Math.max(minEndTick, to.span.start_tick + minTick);
      }
    }
    if (candidate.creation.to_element_id === element.element_id) {
      const from = timeline.elements_by_id[candidate.creation.from_element_id];
      if (from) {
        maxStartTick = Math.min(
          maxStartTick,
          from.span.start_tick + from.span.duration_tick - minTick,
        );
      }
    }
  }
  return { minEndTick, maxStartTick };
}

/**
 * Resolve a pointer drag on an element block into a validated span.
 * Transitions are clamped inside their from/to overlap window; every result
 * keeps start_tick >= 0 and duration >= the 0.1s floor.
 */
export function resolveSpanDrag(options: {
  timeline: TimelineDocument;
  element: TimelineElementDocument;
  mode: SpanDragMode;
  originSpan: TimelineSpanDocument;
  deltaTick: number;
  snapEnabled: boolean;
  snapTicks: number[];
  snapThresholdTick: number;
}): SpanDragResult {
  const {
    timeline,
    element,
    mode,
    originSpan,
    deltaTick,
    snapEnabled,
    snapTicks,
    snapThresholdTick,
  } = options;
  const minTick = minDurationTick(timeline.ticks_per_second);
  const originEnd = originSpan.start_tick + originSpan.duration_tick;
  const window =
    element.creation.type === "transition"
      ? transitionOverlapWindow(timeline, element)
      : null;
  const partner =
    element.creation.type === "transition"
      ? null
      : transitionPartnerBounds(timeline, element);
  let snapTick: number | null = null;

  const snapEdge = (value: number): number => {
    if (!snapEnabled) return value;
    const result = snapAdjust(value, snapTicks, snapThresholdTick);
    if (result.snapped !== null) snapTick = result.snapped;
    return result.tick;
  };

  if (mode === "move") {
    let nextStart = originSpan.start_tick + deltaTick;
    // Snap either edge; prefer the closer adjustment.
    if (snapEnabled) {
      const bySt = snapAdjust(nextStart, snapTicks, snapThresholdTick);
      const byEnd = snapAdjust(
        nextStart + originSpan.duration_tick,
        snapTicks,
        snapThresholdTick,
      );
      if (
        bySt.snapped !== null &&
        (byEnd.snapped === null ||
          Math.abs(bySt.tick - nextStart) <=
            Math.abs(byEnd.tick - originSpan.duration_tick - nextStart))
      ) {
        nextStart = bySt.tick;
        snapTick = bySt.snapped;
      } else if (byEnd.snapped !== null) {
        nextStart = byEnd.tick - originSpan.duration_tick;
        snapTick = byEnd.snapped;
      }
    }
    nextStart = Math.max(0, Math.round(nextStart));
    if (window) {
      const maxStart = window.endTick - originSpan.duration_tick;
      nextStart = Math.min(
        Math.max(nextStart, window.startTick),
        Math.max(window.startTick, maxStart),
      );
    }
    if (partner) {
      // Keep the minimum overlap with every bridged partner on both sides.
      if (Number.isFinite(partner.minEndTick)) {
        nextStart = Math.max(
          nextStart,
          partner.minEndTick - originSpan.duration_tick,
        );
      }
      if (Number.isFinite(partner.maxStartTick)) {
        nextStart = Math.min(nextStart, partner.maxStartTick);
      }
      nextStart = Math.max(0, nextStart);
    }
    return {
      span: {
        ...originSpan,
        start_tick: nextStart,
        duration_tick: originSpan.duration_tick,
      },
      snapTick,
    };
  }

  if (mode === "trim-start") {
    let nextStart = snapEdge(originSpan.start_tick + deltaTick);
    nextStart = Math.round(nextStart);
    const lowBound = window ? window.startTick : 0;
    nextStart = Math.max(lowBound, Math.min(nextStart, originEnd - minTick));
    if (partner && Number.isFinite(partner.maxStartTick)) {
      nextStart = Math.min(nextStart, partner.maxStartTick);
    }
    nextStart = Math.max(0, nextStart);
    return {
      span: {
        ...originSpan,
        start_tick: nextStart,
        duration_tick: originEnd - nextStart,
      },
      snapTick,
    };
  }

  let nextEnd = snapEdge(originEnd + deltaTick);
  nextEnd = Math.round(nextEnd);
  const highBound = window ? window.endTick : Number.POSITIVE_INFINITY;
  nextEnd = Math.min(
    highBound,
    Math.max(nextEnd, originSpan.start_tick + minTick),
  );
  if (partner && Number.isFinite(partner.minEndTick)) {
    nextEnd = Math.max(nextEnd, partner.minEndTick);
  }
  return {
    span: {
      ...originSpan,
      start_tick: originSpan.start_tick,
      duration_tick: nextEnd - originSpan.start_tick,
    },
    snapTick,
  };
}

/**
 * After moving/trimming elements, transitions attached to them must stay
 * inside the new from/to overlap. Returns the extra span changes needed, or a
 * veto when a transition would lose its overlap entirely.
 */
export function transitionFollowChanges(
  timeline: TimelineDocument,
  primaryChanges: SpanChange[],
): TransitionFollowResult {
  const overrides = new Map<string, TimelineSpanDocument>(
    primaryChanges.map((change) => [change.elementId, change.span]),
  );
  const changedIds = new Set(primaryChanges.map((change) => change.elementId));
  const followups: SpanChange[] = [];
  for (const element of Object.values(timeline.elements_by_id)) {
    if (element.creation.type !== "transition" || !element.enabled) continue;
    if (changedIds.has(element.element_id)) continue;
    const { from_element_id: fromId, to_element_id: toId } = element.creation;
    if (!changedIds.has(fromId) && !changedIds.has(toId)) continue;
    const fromExists = Boolean(timeline.elements_by_id[fromId]);
    const toExists = Boolean(timeline.elements_by_id[toId]);
    if (!fromExists || !toExists) continue;
    const window = transitionOverlapWindow(timeline, element, overrides);
    if (!window) {
      return {
        ok: false,
        reason: i18n.t("lib.transitionOverlapError", {
          name: element.label || element.element_id,
        }),
      };
    }
    const minTick = minDurationTick(timeline.ticks_per_second);
    const available = window.endTick - window.startTick;
    const duration = Math.max(
      minTick,
      Math.min(element.span.duration_tick, available),
    );
    const start = Math.min(
      Math.max(element.span.start_tick, window.startTick),
      window.endTick - duration,
    );
    if (
      start !== element.span.start_tick ||
      duration !== element.span.duration_tick
    ) {
      followups.push({
        elementId: element.element_id,
        span: {
          ...element.span,
          start_tick: start,
          duration_tick: duration,
        },
      });
    }
  }
  return { ok: true, changes: followups };
}

function spanPointer(
  timelineId: string,
  elementId: string,
  field: "start_tick" | "duration_tick",
): string {
  return projectJsonPointer(
    "timelines",
    "items",
    timelineId,
    "elements_by_id",
    elementId,
    "span",
    field,
  );
}

/**
 * JSON Patch operations for span changes. `before` values always come from the
 * authoritative snapshot so the CAS hash matches the server document.
 */
export function buildSpanOperations(
  authorityTimeline: TimelineDocument,
  timelineId: string,
  changes: SpanChange[],
): ProjectEditOperation[] {
  const operations: ProjectEditOperation[] = [];
  for (const change of changes) {
    const element = authorityTimeline.elements_by_id[change.elementId];
    if (!element) continue;
    if (element.span.start_tick !== change.span.start_tick) {
      operations.push({
        op: "replace",
        path: spanPointer(timelineId, change.elementId, "start_tick"),
        before: element.span.start_tick,
        value: change.span.start_tick,
      });
    }
    if (element.span.duration_tick !== change.span.duration_tick) {
      operations.push({
        op: "replace",
        path: spanPointer(timelineId, change.elementId, "duration_tick"),
        before: element.span.duration_tick,
        value: change.span.duration_tick,
      });
    }
  }
  return operations;
}

export interface TransitionJunction {
  transition: TimelineElementDocument;
  fromId: string;
  toId: string;
  centerTick: number;
}

/**
 * Split transitions into junction badges (both endpoints resolvable) and
 * orphans that must still occupy an ordinary track row.
 */
export function splitTransitionsForDisplay(timeline: TimelineDocument): {
  junctions: TransitionJunction[];
  orphanTransitionIds: Set<string>;
} {
  const junctions: TransitionJunction[] = [];
  const orphanTransitionIds = new Set<string>();
  for (const element of Object.values(timeline.elements_by_id)) {
    if (element.creation.type !== "transition") continue;
    const fromId = element.creation.from_element_id;
    const toId = element.creation.to_element_id;
    if (timeline.elements_by_id[fromId] && timeline.elements_by_id[toId]) {
      junctions.push({
        transition: element,
        fromId,
        toId,
        centerTick: element.span.start_tick + element.span.duration_tick / 2,
      });
    } else {
      orphanTransitionIds.add(element.element_id);
    }
  }
  return { junctions, orphanTransitionIds };
}

/**
 * Compute ripple changes: disabled. Elements stay in their original positions.
 */
export function computeRippleChanges(
  _timeline: TimelineDocument,
  _primaryChanges: SpanChange[],
): SpanChange[] {
  return [];
}
