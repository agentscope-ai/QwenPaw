import { create } from "zustand";
import type {
  ProjectDocument,
  TimelineSpanDocument,
} from "@/contracts/creator";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";

export interface EditTargetInfo {
  kind:
    | "element"
    | "timeline"
    | "artifact-slot"
    | "visual-entity"
    | "strategy"
    | "settings"
    | "source"
    | "other";
  id: string | null;
  label: string | null;
}

export interface UserEditEntry {
  at: string;
  op: "add" | "replace" | "remove";
  path: string;
  target: EditTargetInfo;
  field: string;
  before?: unknown;
  after?: unknown;
}

export interface AffectedRange {
  startTick: number;
  endTick: number;
}

export interface UserEditsContext {
  count: number;
  truncated: number;
  edits: UserEditEntry[];
  lastEntryAt: string | null;
}

interface CreatorEditBufferState {
  projectId: string | null;
  entries: UserEditEntry[];
  /** Time ranges whose old final-render frames no longer match, per timeline. */
  affectedRangesByTimeline: Record<string, AffectedRange[]>;
  lastRecordGeneration: number | null;
  recordPatch: (input: {
    projectId: string;
    projectBefore: ProjectDocument | null;
    operations: ProjectEditOperation[];
    generation: number;
  }) => void;
  /** Compact context for the next AgentDock message; does not clear. */
  consumeContext: (projectId: string) => UserEditsContext | null;
  /** Clear entries after they were delivered with a user message. */
  markFlushed: (projectId: string, upToEntryAt?: string | null) => void;
  clearAffectedRanges: (timelineId: string, throughGeneration: number) => void;
  reset: () => void;
}

const MAX_ENTRIES = 200;
const MAX_CONTEXT_EDITS = 40;
const MAX_VALUE_CHARS = 120;

function compactValue(value: unknown): unknown {
  if (value === undefined) return undefined;
  if (value === null || typeof value === "number" || typeof value === "boolean")
    return value;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (typeof text !== "string") return undefined;
  return text.length > MAX_VALUE_CHARS
    ? `${text.slice(0, MAX_VALUE_CHARS)}…(${text.length} chars)`
    : text;
}

function parsePointer(path: string): string[] {
  return path
    .split("/")
    .slice(1)
    .map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
}

function describeTarget(
  tokens: string[],
  project: ProjectDocument | null,
): EditTargetInfo {
  if (
    tokens[0] === "timelines" &&
    tokens[3] === "elements_by_id" &&
    tokens[4]
  ) {
    const timeline = project?.timelines.items[tokens[2]];
    const element = timeline?.elements_by_id[tokens[4]];
    return {
      kind: "element",
      id: tokens[4],
      label: element?.label || tokens[4],
    };
  }
  if (tokens[0] === "timelines" && tokens[2]) {
    return { kind: "timeline", id: tokens[2], label: tokens[2] };
  }
  if (tokens[0] === "assets" && tokens[1] === "artifact_slots_by_id") {
    return {
      kind: "artifact-slot",
      id: tokens[2] ?? null,
      label: tokens[2] ?? null,
    };
  }
  if (tokens[0] === "visual" && tokens[1] === "entities" && tokens[3]) {
    const entity = project?.visual.entities.items[tokens[3]];
    return {
      kind: "visual-entity",
      id: tokens[3],
      label: entity?.name || tokens[3],
    };
  }
  if (tokens[0] === "strategy")
    return { kind: "strategy", id: null, label: null };
  if (tokens[0] === "settings")
    return { kind: "settings", id: null, label: null };
  if (tokens[0] === "sources") {
    return { kind: "source", id: tokens[2] ?? null, label: tokens[2] ?? null };
  }
  return { kind: "other", id: null, label: null };
}

function fieldSuffix(tokens: string[]): string {
  if (tokens[0] === "timelines" && tokens[3] === "elements_by_id") {
    return tokens.slice(5).join("/") || "(element)";
  }
  return tokens.join("/");
}

function spanFromRecord(value: unknown): TimelineSpanDocument | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const start = record.start_tick;
  const duration = record.duration_tick;
  return typeof start === "number" && typeof duration === "number"
    ? { start_tick: start, duration_tick: duration }
    : null;
}

function mergeRange(
  ranges: AffectedRange[],
  next: AffectedRange,
): AffectedRange[] {
  const merged: AffectedRange[] = [];
  let current = { ...next };
  for (const range of ranges) {
    if (
      range.endTick < current.startTick ||
      range.startTick > current.endTick
    ) {
      merged.push(range);
    } else {
      current = {
        startTick: Math.min(range.startTick, current.startTick),
        endTick: Math.max(range.endTick, current.endTick),
      };
    }
  }
  merged.push(current);
  return merged.sort((left, right) => left.startTick - right.startTick);
}

/**
 * Collect the timeline ranges invalidated by this patch: for every touched
 * element, the union of its span before and after the edit. Old final-render
 * frames inside these ranges must not be reused even if the element has moved
 * elsewhere by now.
 */
function collectAffectedRanges(
  operations: ProjectEditOperation[],
  project: ProjectDocument | null,
): Array<{ timelineId: string; range: AffectedRange }> {
  const perElement = new Map<string, { timelineId: string; ticks: number[] }>();
  for (const operation of operations) {
    const tokens = parsePointer(operation.path);
    if (tokens[0] !== "timelines" || tokens[3] !== "elements_by_id") continue;
    const timelineId = tokens[2];
    const elementId = tokens[4];
    if (!timelineId || !elementId) continue;
    const key = `${timelineId}\u0000${elementId}`;
    let bucket = perElement.get(key);
    if (!bucket) {
      bucket = { timelineId, ticks: [] };
      perElement.set(key, bucket);
      const before =
        project?.timelines.items[timelineId]?.elements_by_id[elementId];
      if (before) {
        bucket.ticks.push(
          before.span.start_tick,
          before.span.start_tick + before.span.duration_tick,
        );
      }
    }
    // Span edits contribute the new edge; whole-element add/remove carries a
    // span object inside the value/before payload.
    const suffix = tokens.slice(5);
    if (suffix[0] === "span" && typeof operation.value === "number") {
      const before =
        project?.timelines.items[timelineId]?.elements_by_id[elementId];
      if (before) {
        const nextSpan = { ...before.span } as TimelineSpanDocument;
        if (suffix[1] === "start_tick") nextSpan.start_tick = operation.value;
        if (suffix[1] === "duration_tick")
          nextSpan.duration_tick = operation.value;
        bucket.ticks.push(
          nextSpan.start_tick,
          nextSpan.start_tick + nextSpan.duration_tick,
        );
      }
    } else if (suffix.length === 0) {
      const added = spanFromRecord(
        (operation.value as Record<string, unknown> | undefined)?.span,
      );
      if (added)
        bucket.ticks.push(
          added.start_tick,
          added.start_tick + added.duration_tick,
        );
      const removed = spanFromRecord(
        (operation.before as Record<string, unknown> | undefined)?.span,
      );
      if (removed)
        bucket.ticks.push(
          removed.start_tick,
          removed.start_tick + removed.duration_tick,
        );
    }
  }
  const results: Array<{ timelineId: string; range: AffectedRange }> = [];
  perElement.forEach((bucket) => {
    if (!bucket.ticks.length) return;
    results.push({
      timelineId: bucket.timelineId,
      range: {
        startTick: Math.min(...bucket.ticks),
        endTick: Math.max(...bucket.ticks),
      },
    });
  });
  return results;
}

export const useCreatorEditBufferStore = create<CreatorEditBufferState>(
  (set, get) => ({
    projectId: null,
    entries: [],
    affectedRangesByTimeline: {},
    lastRecordGeneration: null,
    recordPatch: ({ projectId, projectBefore, operations, generation }) => {
      const at = new Date().toISOString();
      const nextEntries = operations.map<UserEditEntry>((operation) => {
        const tokens = parsePointer(operation.path);
        return {
          at,
          op: operation.op,
          path: operation.path,
          target: describeTarget(tokens, projectBefore),
          field: fieldSuffix(tokens),
          ...(operation.op !== "add"
            ? { before: compactValue(operation.before) }
            : {}),
          ...(operation.op !== "remove"
            ? { after: compactValue(operation.value) }
            : {}),
        };
      });
      const affected = collectAffectedRanges(operations, projectBefore);
      set((state) => {
        const sameProject = state.projectId === projectId;
        const entries = [
          ...(sameProject ? state.entries : []),
          ...nextEntries,
        ].slice(-MAX_ENTRIES);
        const ranges = sameProject ? { ...state.affectedRangesByTimeline } : {};
        affected.forEach(({ timelineId, range }) => {
          ranges[timelineId] = mergeRange(ranges[timelineId] ?? [], range);
        });
        return {
          projectId,
          entries,
          affectedRangesByTimeline: ranges,
          lastRecordGeneration: generation,
        };
      });
    },
    consumeContext: (projectId) => {
      const state = get();
      if (state.projectId !== projectId || !state.entries.length) return null;
      const edits = state.entries.slice(-MAX_CONTEXT_EDITS);
      return {
        count: state.entries.length,
        truncated: Math.max(0, state.entries.length - edits.length),
        edits,
        lastEntryAt: state.entries.at(-1)?.at ?? null,
      };
    },
    markFlushed: (projectId, upToEntryAt) => {
      set((state) => {
        if (state.projectId !== projectId) return {};
        if (!upToEntryAt) return { entries: [] };
        return {
          entries: state.entries.filter((entry) => entry.at > upToEntryAt),
        };
      });
    },
    clearAffectedRanges: (timelineId, throughGeneration) => {
      set((state) => {
        if (
          state.lastRecordGeneration !== null &&
          throughGeneration < state.lastRecordGeneration
        ) {
          return {};
        }
        if (!state.affectedRangesByTimeline[timelineId]?.length) return {};
        const ranges = { ...state.affectedRangesByTimeline };
        delete ranges[timelineId];
        return { affectedRangesByTimeline: ranges };
      });
    },
    reset: () =>
      set({
        projectId: null,
        entries: [],
        affectedRangesByTimeline: {},
        lastRecordGeneration: null,
      }),
  }),
);
