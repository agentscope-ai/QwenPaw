import type { ProjectDocument, TimelineDocument } from "@/contracts/creator";
import type { ProjectEditOperation } from "@/store/projectSnapshotStore";

let _counter = 0;
function nextTimelineId(project: ProjectDocument): string {
  _counter += 1;
  const base = `timeline:${_counter}`;
  if (!project.timelines.items[base]) return base;
  return `timeline:${Date.now()}-${_counter}`;
}

export function createTimelineOperations(
  project: ProjectDocument,
  name: string,
): { timelineId: string; operations: ProjectEditOperation[] } {
  const timelineId = nextTimelineId(project);
  const timeline: TimelineDocument = {
    timeline_id: timelineId,
    name,
    description: "",
    ticks_per_second: 1000,
    color_grade: "",
    edit_plan: null,
    elements_by_id: {},
  };
  const orderIndex = project.timelines.order.length;
  return {
    timelineId,
    operations: [
      {
        op: "add",
        path: `/timelines/items/${timelineId}`,
        value: timeline,
        missingBefore: true,
      },
      {
        op: "add",
        path: `/timelines/order/${orderIndex}`,
        value: timelineId,
        missingBefore: true,
      },
    ],
  };
}

export function renameTimelineOperations(
  timelineId: string,
  name: string,
): ProjectEditOperation[] {
  return [
    {
      op: "replace",
      path: `/timelines/items/${timelineId}/name`,
      value: name,
    },
  ];
}

export function deleteTimelineOperations(
  project: ProjectDocument,
  timelineId: string,
): ProjectEditOperation[] {
  if (!project.timelines.order.includes(timelineId)) return [];
  // A base timeline takes its snapshots with it — the snapshot panel only
  // lists the current timeline's prefix, so survivors would be unreachable.
  const doomed = new Set([
    timelineId,
    ...project.timelines.order.filter((id) =>
      id.startsWith(`${SNAPSHOT_PREFIX}${timelineId}:`),
    ),
  ]);
  const operations: ProjectEditOperation[] = [];
  for (const id of doomed) {
    operations.push({
      op: "remove",
      path: `/timelines/items/${id}`,
      before: project.timelines.items[id],
    });
  }
  // Descending order indices: removing a lower index first would shift the
  // later ones and make their `before` hashes miss.
  const indices = project.timelines.order
    .map((id, index) => ({ id, index }))
    .filter(({ id }) => doomed.has(id))
    .sort((a, b) => b.index - a.index);
  for (const { id, index } of indices) {
    operations.push({
      op: "remove",
      path: `/timelines/order/${index}`,
      before: id,
    });
  }
  return operations;
}

export function duplicateTimelineOperations(
  project: ProjectDocument,
  sourceId: string,
  name: string,
): { timelineId: string; operations: ProjectEditOperation[] } {
  const source = project.timelines.items[sourceId];
  if (!source) {
    return createTimelineOperations(project, name);
  }
  const timelineId = nextTimelineId(project);
  const copy: TimelineDocument = {
    ...source,
    timeline_id: timelineId,
    name,
    description: source.description,
    elements_by_id: {},
  };
  const orderIndex = project.timelines.order.length;
  return {
    timelineId,
    operations: [
      {
        op: "add",
        path: `/timelines/items/${timelineId}`,
        value: copy,
        missingBefore: true,
      },
      {
        op: "add",
        path: `/timelines/order/${orderIndex}`,
        value: timelineId,
        missingBefore: true,
      },
    ],
  };
}

// ── Timeline snapshots (design 84:039752 历史快照) ─────────────────────
// A snapshot is a frozen Timeline copy stored under `snapshot:{tid}:{n}`
// with element ids remapped to stay globally unique (mirrors the backend's
// auto_snapshot_timelines remapping).

const SNAPSHOT_PREFIX = "snapshot:";

/** Snapshots of one base timeline, newest first. */
export function listTimelineSnapshots(
  project: ProjectDocument,
  timelineId: string,
): TimelineDocument[] {
  const prefix = `${SNAPSHOT_PREFIX}${timelineId}:`;
  return project.timelines.order
    .filter((id) => id.startsWith(prefix))
    .map((id) => project.timelines.items[id])
    .filter(Boolean)
    .reverse();
}

function remapElementId(elementId: string, snapshotId: string): string {
  return `${snapshotId}:${elementId}`;
}

function remapSlotId(slotId: string, snapshotId: string): string {
  if (!slotId.startsWith("element:")) return slotId;
  const parts = slotId.split(":");
  const rest = parts.slice(2).join(":");
  return `element:${remapElementId(parts[1], snapshotId)}${
    rest ? `:${rest}` : ""
  }`;
}

type MutableElement = Record<string, unknown> & {
  element_id: string;
  outputs?: Record<string, { slot_id?: string }>;
  render_source?: { type?: string; element_id?: string } | null;
  creation?: {
    type?: string;
    from_element_id?: string;
    to_element_id?: string;
  };
};

/** Deep-copy a timeline into a snapshot, remapping element-scoped ids. */
function snapshotTimelineCopy(
  source: TimelineDocument,
  snapshotId: string,
  name: string,
): TimelineDocument {
  const copy = structuredClone(source) as TimelineDocument & {
    edit_plan?: { scene_ledger?: Array<{ element_ids?: string[] }> } | null;
  };
  copy.timeline_id = snapshotId;
  copy.name = name;
  const remapped: Record<string, MutableElement> = {};
  for (const [oldId, element] of Object.entries(
    copy.elements_by_id as Record<string, MutableElement>,
  )) {
    const newId = remapElementId(oldId, snapshotId);
    element.element_id = newId;
    for (const output of Object.values(element.outputs ?? {})) {
      if (output.slot_id)
        output.slot_id = remapSlotId(output.slot_id, snapshotId);
    }
    const renderSource = element.render_source;
    if (
      renderSource &&
      renderSource.type === "element_output" &&
      renderSource.element_id
    ) {
      renderSource.element_id = remapElementId(
        renderSource.element_id,
        snapshotId,
      );
    }
    const creation = element.creation;
    if (creation?.type === "transition") {
      if (creation.from_element_id)
        creation.from_element_id = remapElementId(
          creation.from_element_id,
          snapshotId,
        );
      if (creation.to_element_id)
        creation.to_element_id = remapElementId(
          creation.to_element_id,
          snapshotId,
        );
    }
    remapped[newId] = element;
  }
  copy.elements_by_id =
    remapped as unknown as TimelineDocument["elements_by_id"];
  for (const row of copy.edit_plan?.scene_ledger ?? []) {
    if (row.element_ids)
      row.element_ids = row.element_ids.map((id) =>
        remapElementId(id, snapshotId),
      );
  }
  return copy;
}

/** Manually snapshot the timeline's current state under the given name. */
export function createSnapshotOperations(
  project: ProjectDocument,
  timelineId: string,
  name: string,
): ProjectEditOperation[] {
  const source = project.timelines.items[timelineId];
  if (!source) return [];
  const prefix = `${SNAPSHOT_PREFIX}${timelineId}:`;
  // Max suffix + 1, not count + 1: snapshots are deletable, and counting
  // after a deletion would collide with a surviving snapshot id.
  const highest = project.timelines.order
    .filter((id) => id.startsWith(prefix))
    .reduce((max, id) => {
      const suffix = Number(id.slice(prefix.length));
      return Number.isInteger(suffix) ? Math.max(max, suffix) : max;
    }, 0);
  const snapshotId = `${prefix}${highest + 1}`;
  const orderIndex = project.timelines.order.length;
  return [
    {
      op: "add",
      path: `/timelines/items/${snapshotId}`,
      value: snapshotTimelineCopy(source, snapshotId, name),
      missingBefore: true,
    },
    {
      op: "add",
      path: `/timelines/order/${orderIndex}`,
      value: snapshotId,
      missingBefore: true,
    },
  ];
}

/** Restore a snapshot's content back onto its base timeline. */
export function restoreSnapshotOperations(
  project: ProjectDocument,
  snapshotId: string,
): ProjectEditOperation[] {
  const snapshot = project.timelines.items[snapshotId];
  const baseId = snapshotId.startsWith(SNAPSHOT_PREFIX)
    ? snapshotId.slice(SNAPSHOT_PREFIX.length).replace(/:\d+$/, "")
    : null;
  const base = baseId ? project.timelines.items[baseId] : null;
  if (!snapshot || !base || !baseId) return [];
  const stripPrefix = `${snapshotId}:`;
  const strip = (value: string) =>
    value.startsWith(stripPrefix) ? value.slice(stripPrefix.length) : value;
  const restored: Record<string, MutableElement> = {};
  const clone = structuredClone(snapshot) as TimelineDocument & {
    edit_plan?: { scene_ledger?: Array<{ element_ids?: string[] }> } | null;
  };
  for (const [snapId, element] of Object.entries(
    clone.elements_by_id as Record<string, MutableElement>,
  )) {
    const restoredId = strip(snapId);
    element.element_id = restoredId;
    for (const output of Object.values(element.outputs ?? {})) {
      if (output.slot_id?.startsWith("element:")) {
        const parts = output.slot_id.split(":");
        // element:{snapshotId}:{origId}[:name] — strip the snapshot infix.
        output.slot_id = output.slot_id.replace(
          `element:${stripPrefix}`,
          "element:",
        );
        void parts;
      }
    }
    const renderSource = element.render_source;
    if (
      renderSource &&
      renderSource.type === "element_output" &&
      renderSource.element_id
    ) {
      renderSource.element_id = strip(renderSource.element_id);
    }
    const creation = element.creation;
    if (creation?.type === "transition") {
      if (creation.from_element_id)
        creation.from_element_id = strip(creation.from_element_id);
      if (creation.to_element_id)
        creation.to_element_id = strip(creation.to_element_id);
    }
    restored[restoredId] = element;
  }
  const editPlan = clone.edit_plan ?? null;
  for (const row of editPlan?.scene_ledger ?? []) {
    if (row.element_ids) row.element_ids = row.element_ids.map(strip);
  }
  return [
    {
      op: "replace",
      path: `/timelines/items/${baseId}/elements_by_id`,
      before: base.elements_by_id,
      value: restored,
    },
    {
      op: "replace",
      path: `/timelines/items/${baseId}/edit_plan`,
      before: base.edit_plan ?? null,
      value: editPlan,
    },
    {
      op: "replace",
      path: `/timelines/items/${baseId}/color_grade`,
      before: base.color_grade ?? "",
      value: (snapshot.color_grade ?? "") as string,
    },
  ];
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** Whether the base timeline's current content equals this snapshot —
 *  i.e. applying it would be a no-op. Powers the "已应用" badge so the user
 *  can see which version the live timeline currently matches. */
export function snapshotMatchesTimeline(
  project: ProjectDocument,
  snapshotId: string,
): boolean {
  const operations = restoreSnapshotOperations(project, snapshotId);
  if (!operations.length) return false;
  // Cheap short-circuit before the full canonical comparison: differing
  // element counts can never match, and the panel recomputes on every poll.
  const [elementsOp] = operations;
  const beforeKeys = Object.keys(
    (elementsOp.before ?? {}) as Record<string, unknown>,
  );
  const valueKeys = Object.keys(
    (elementsOp.value ?? {}) as Record<string, unknown>,
  );
  if (beforeKeys.length !== valueKeys.length) return false;
  return operations.every(
    (operation) =>
      stableStringify(operation.before ?? null) ===
      stableStringify(operation.value ?? null),
  );
}
