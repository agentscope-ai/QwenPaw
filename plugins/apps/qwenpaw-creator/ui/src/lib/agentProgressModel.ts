import type {
  ProjectDocument,
  SpecialistRunView,
  TaskView,
  WorkGraphNode,
  WorkGraphView,
} from "@/contracts/creator";
import { selectLiveTimelineIds } from "@/selectors/timelineElementSelectors";
import {
  creatorRoleLabel,
  creatorStatusLabel,
  creatorTargetLabel,
  creatorWorkNodeLabel,
  taskKindLabel,
} from "@/lib/creatorPresentation";
import i18n from "@/i18n";
import { projectJsonPointer } from "@/lib/projectJsonPointer";

export type AgentProgressPhase =
  | "preparing"
  | "running"
  | "attention"
  | "completed";
export interface AgentProgressCounts {
  total: number;
  preparing: number;
  running: number;
  attention: number;
  completed: number;
}
export interface AgentProgressItem {
  id: string;
  source: "graph" | "run" | "task";
  label: string;
  statusLabel: string;
  status: string;
  phase: AgentProgressPhase;
  locator: Record<string, string> | null;
  progressPercent: number | null;
  node?: WorkGraphNode;
  run?: SpecialistRunView;
  task?: TaskView;
}
export interface AgentProgressGroup {
  id: string;
  kind: "timeline" | "source" | "project";
  label: string;
  locator: Record<string, string> | null;
  items: AgentProgressItem[];
  counts: AgentProgressCounts;
}
export interface AgentProgressInput {
  projectId: string;
  graph: WorkGraphView | null;
  runs: SpecialistRunView[];
  tasks: TaskView[];
  project: ProjectDocument | null;
}
const phaseOrder: Record<AgentProgressPhase, number> = {
  running: 0,
  attention: 1,
  preparing: 2,
  completed: 3,
};
const graphStates: Record<string, string> = {
  done: "done",
  running: "running",
  waiting_review: "waiting_review",
  failed: "failed",
  gated: "waitingDeps",
  ready: "ready",
  stale: "stale",
};
const coreTasks = new Set([
  "asset_ingest",
  "asset_import",
  "source_intelligence",
  "source_memory_build",
  "image_generation",
  "r2v_generation",
  "ai_edit_plan",
  "ai_edit_execute",
  "compose",
  "script_draft",
]);

const emptyCounts = (): AgentProgressCounts => ({
  total: 0,
  preparing: 0,
  running: 0,
  attention: 0,
  completed: 0,
});
function countsOf(items: AgentProgressItem[]) {
  const counts = emptyCounts();
  for (const item of items) {
    counts.total++;
    counts[item.phase]++;
  }
  return counts;
}
function phaseOf(status: string): AgentProgressPhase {
  if (["done", "SUCCEEDED"].includes(status)) return "completed";
  if (
    ["running", "RUNNING", "RUNNING_MODEL", "WAITING_RUNTIME"].includes(status)
  )
    return "running";
  if (["ready", "gated", "QUEUED", "QUEUED_CAPACITY"].includes(status))
    return "preparing";
  return "attention";
}
function percent(value: number | null, phase: AgentProgressPhase) {
  return phase === "running" &&
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
    ? Math.round(value * 100)
    : null;
}
function isLater(a: { createdAt?: string }, b: { createdAt?: string }) {
  const x = Date.parse(a.createdAt ?? ""),
    y = Date.parse(b.createdAt ?? "");
  return Number.isFinite(x) && Number.isFinite(y) && x > y;
}

function taskOrderTime(task: TaskView): number {
  // A Task identity survives an authorized retry. Creation orders distinct
  // identities; updatedAt is the fallback for older API records without it.
  const created = Date.parse(task.createdAt ?? "");
  return Number.isFinite(created) ? created : Date.parse(task.updatedAt ?? "");
}

function latestLinkedTask(
  tasks: TaskView[],
  node: WorkGraphNode,
): TaskView | null {
  const exact = tasks.find((task) => task.id === node.taskId);
  if (exact) return exact;
  if (tasks.length === 1) return tasks[0];
  if (!tasks.length) return null;
  if (tasks.some((task) => !Number.isFinite(taskOrderTime(task)))) {
    return null;
  }
  const ordered = [...tasks].sort(
    (a, b) => taskOrderTime(b) - taskOrderTime(a),
  );
  if (taskOrderTime(ordered[0]) === taskOrderTime(ordered[1])) return null;
  return ordered[0];
}

function composeNeedsUpdate(
  node: WorkGraphNode,
  project: ProjectDocument | null,
  graphGeneration: number,
): boolean {
  if (
    !project ||
    node.kind !== "compose" ||
    !["ready", "gated", "stale"].includes(node.status)
  )
    return false;
  const timelineId = node.timelineId ?? node.locator?.timelineId;
  if (!timelineId) return false;
  const slot =
    project.assets.artifact_slots_by_id?.[`timeline:${timelineId}:render`];
  const version = slot?.selected_version_id
    ? project.assets.artifact_versions_by_id[slot.selected_version_id]
    : null;
  if (slot?.kind !== "final_video" || version?.kind !== "final_video")
    return false;
  // Execution deliberately reopens an outdated render as READY / GATED so
  // automatic composition can resume once its inputs are ready. Preserve
  // that recipe, but present the existing result as needing an update.
  // A current graph can also reject changed frozen inputs without a stale
  // flag. An older graph cannot disprove a newly published result.
  return version.stale || graphGeneration >= project.generation;
}

/** Enrich an operation's real target with the field edited to produce it.
 * Keep the backend node untouched: its locator still belongs to dispatch. */
function operationLocator(
  kind: string,
  locator: Record<string, string>,
  project: ProjectDocument | null,
  nodeId?: string,
): Record<string, string> {
  const result = { ...locator };
  const { timelineId, elementId, assetId } = result;
  if (kind === "script" || kind === "script_draft") {
    return { ...result, page: "blueprint" };
  }
  if (
    timelineId &&
    elementId &&
    ["storyboard", "video", "image_generation", "r2v_generation"].includes(kind)
  ) {
    result.page = "element";
    const creation =
      project?.timelines.items[timelineId]?.elements_by_id?.[elementId]
        ?.creation;
    const storyboard = kind === "storyboard" || kind === "image_generation";
    const field = storyboard
      ? creation?.type === "r2v"
        ? "storyboard_prompt"
        : null
      : creation?.type === "s2v"
      ? "script"
      : ["r2v", "t2v", "i2v"].includes(creation?.type ?? "")
      ? "video_prompt"
      : null;
    // An independently refreshed graph may precede the project snapshot.
    // Preserve its scoped workbench route, but do not invent a missing field.
    if (field)
      result.field = projectJsonPointer(
        "timelines",
        "items",
        timelineId,
        "elements_by_id",
        elementId,
        "creation",
        field,
      );
  } else if (kind === "visual" && assetId && nodeId) {
    const entity = project?.visual.entities.items[assetId];
    // Entity and variant ids contain colons; reconstruct the canonical node
    // identity from actual variants instead of splitting or guessing default.
    const matches =
      entity?.variants?.order.filter(
        (variantId) =>
          entity.variants.items[variantId] &&
          nodeId === `visual:${assetId}:${variantId}`,
      ) ?? [];
    if (matches.length === 1) {
      result.variantId = matches[0];
      result.field = projectJsonPointer(
        "visual",
        "entities",
        "items",
        assetId,
        "variants",
        "items",
        matches[0],
        "prompt",
      );
    }
  } else if (kind === "lineup" && nodeId?.startsWith("lineup:")) {
    const lineupId = nodeId.slice("lineup:".length);
    if (project?.visual.cast_lineups?.items[lineupId])
      result.assetId = lineupId;
  }
  return result;
}

/** A projection of durable operations. This adds no execution phase or backend identity. */
export function buildAgentProgressModel(input: AgentProgressInput): {
  groups: AgentProgressGroup[];
  counts: AgentProgressCounts;
} {
  const { projectId } = input;
  const project =
    input.project?.project_id === projectId ? input.project : null;
  const liveIds = project ? selectLiveTimelineIds(project) : [];
  // Graph and project snapshots refresh independently. A newer graph can
  // already contain a newly created episode while the project store catches up.
  const newerGraphTimelineIds =
    project &&
    input.graph?.projectId === projectId &&
    input.graph.generation > project.generation
      ? [
          ...new Set(
            input.graph.nodes.flatMap((node) => {
              const id = node.timelineId ?? node.locator?.timelineId;
              return id && !id.startsWith("snapshot:") && !liveIds.includes(id)
                ? [id]
                : [];
            }),
          ),
        ]
      : [];
  const displayTimelineIds = [...liveIds, ...newerGraphTimelineIds];
  const live = new Set(displayTimelineIds);
  const explicitTimeline = (id?: string | null): string | null =>
    id && !id.startsWith("snapshot:") && (!project || live.has(id)) ? id : null;
  function timelineOf(ref: string): string | null {
    if (live.has(ref)) return ref;
    if (ref.startsWith("timeline:"))
      return explicitTimeline(ref.slice("timeline:".length));
    if (ref.startsWith("element:")) {
      const eid = ref.slice("element:".length);
      const matches = liveIds.filter(
        (id) => project?.timelines.items[id]?.elements_by_id?.[eid],
      );
      return matches.length === 1 ? matches[0] : null;
    }
    return null;
  }
  const sourceRef = (ref: string) =>
    /^(?:asset-version|asset|source|visual-entity|cast-lineup|lineup):/u.test(
      ref,
    );
  const groups = new Map<string, AgentProgressGroup>();
  function groupFor(
    refs: string[],
    locator?: Record<string, string>,
    preferredTimeline?: string | null,
  ): AgentProgressGroup {
    const timelineIds = new Set(
      refs.map(timelineOf).filter((id): id is string => Boolean(id)),
    );
    const explicit = explicitTimeline(preferredTimeline ?? locator?.timelineId);
    const timelineId =
      explicit ?? (timelineIds.size === 1 ? [...timelineIds][0] : null);
    const source = !timelineId && refs.length > 0 && refs.every(sourceRef);
    const id = timelineId
      ? `timeline:${timelineId}`
      : source
      ? "project:sources"
      : "project:other";
    if (!groups.has(id)) {
      const publicLabel = timelineId
        ? creatorTargetLabel(`timeline:${timelineId}`, project)
        : "";
      const fallback = timelineId
        ? creatorTargetLabel(`timeline:${timelineId}`)
        : "";
      groups.set(id, {
        id,
        kind: timelineId ? "timeline" : source ? "source" : "project",
        label: timelineId
          ? publicLabel !== fallback
            ? publicLabel
            : i18n.t("agentProgress.timeline", {
                index: Math.max(1, displayTimelineIds.indexOf(timelineId) + 1),
              })
          : i18n.t(
              source ? "agentProgress.sources" : "agentProgress.otherWork",
            ),
        locator: timelineId
          ? { page: "plan", timelineId }
          : source
          ? { page: "assets" }
          : null,
        items: [],
        counts: emptyCounts(),
      });
    }
    return groups.get(id)!;
  }
  const nodes =
    input.graph?.projectId === projectId
      ? input.graph.nodes.filter((node) => {
          const tid = node.timelineId ?? node.locator?.timelineId;
          return !tid || Boolean(explicitTimeline(tid));
        })
      : [];
  const tasks = input.tasks.filter((task) => task.projectId === projectId);
  const representedTasks = new Set<string>();
  const linkedTasksByNode = new Map<string, TaskView[]>();
  function nodeMatchesTask(node: WorkGraphNode, task: TaskView) {
    if (node.taskId === task.id) return true;
    const tid = node.timelineId ?? node.locator?.timelineId;
    if (node.kind === "compose" && task.kind === "compose")
      return Boolean(tid && timelineOf(task.targetRef) === tid);
    if (node.kind === "script" && String(task.kind) === "script_draft")
      return Boolean(tid && timelineOf(task.targetRef) === tid);
    if (node.kind === "video" && task.kind === "r2v_generation")
      return Boolean(
        node.locator?.elementId &&
          task.targetRef === `element:${node.locator.elementId}`,
      );
    if (node.kind === "storyboard" && task.kind === "image_generation")
      return Boolean(
        node.locator?.elementId &&
          task.targetRef === `element:${node.locator.elementId}`,
      );
    if (node.kind === "visual" && task.kind === "image_generation")
      return Boolean(
        node.locator?.assetId &&
          [
            `asset:${node.locator.assetId}`,
            `visual-entity:${node.locator.assetId}`,
          ].includes(task.targetRef),
      );
    if (
      node.kind === "lineup" &&
      task.kind === "image_generation" &&
      node.id.startsWith("lineup:")
    )
      return [
        `lineup:${node.id.slice(7)}`,
        `cast-lineup:${node.id.slice(7)}`,
      ].includes(task.targetRef);
    return false;
  }
  for (const task of tasks) {
    const exact = nodes.find((node) => node.taskId === task.id);
    const matches = exact
      ? [exact]
      : nodes.filter((node) => nodeMatchesTask(node, task));
    if (matches.length !== 1) continue;
    representedTasks.add(task.id);
    const linked = linkedTasksByNode.get(matches[0].id) ?? [];
    linked.push(task);
    linkedTasksByNode.set(matches[0].id, linked);
  }
  for (const node of nodes) {
    const locator = node.locator ?? {};
    const tid = explicitTimeline(node.timelineId ?? locator.timelineId);
    const refs = locator.elementId
      ? [`element:${locator.elementId}`]
      : locator.assetId
      ? [`visual-entity:${locator.assetId}`]
      : [];
    const group = groupFor(refs, locator, tid);
    const task = latestLinkedTask(linkedTasksByNode.get(node.id) ?? [], node);
    // The APIs do not expose a shared revision. Prefer the durable active task
    // over an independently read terminal graph; in the opposite refresh order
    // this can conservatively retain activity until the task poll catches up.
    const taskIsActive = task && ["QUEUED", "RUNNING"].includes(task.status);
    // A successful Task cannot reopen (only FAILED Tasks may retry with the
    // same id). Its exact identity proves that this execution has ended even
    // if the graph poll still reports it running. A semantic match cannot
    // establish this, and review / artifact states remain graph-authoritative.
    const exactTaskSucceeded =
      node.status === "running" &&
      node.taskId != null &&
      task?.id === node.taskId &&
      task.status === "SUCCEEDED";
    // READY means the stage may be dispatched, including after a failed
    // composition. The public graph has no failed-attempt identity. Expose a
    // dated latest attempt as history without letting it replace a selected
    // artifact (DONE / WAITING_REVIEW), or a currently running graph node.
    const lastAttemptNeedsAttention =
      task &&
      node.status === "ready" &&
      Number.isFinite(taskOrderTime(task)) &&
      ["FAILED", "QUARANTINED", "CANCELLED"].includes(task.status);
    const projectedTask =
      taskIsActive || exactTaskSucceeded || lastAttemptNeedsAttention
        ? task
        : null;
    const outdatedCompose =
      !projectedTask &&
      composeNeedsUpdate(node, project, input.graph?.generation ?? -1);
    const status =
      projectedTask?.status ?? (outdatedCompose ? "stale" : node.status);
    const promptPreparation =
      !projectedTask &&
      node.status === "gated" &&
      (node.promptSyncRequired ??
        node.missing.some((item) =>
          [
            "镜头与提示词待同步或待审阅确认",
            "镜头生成说明待更新或待审阅确认",
          ].includes(item),
        ));
    const preparationFailed =
      promptPreparation && node.preparationState === "failed";
    const preparationRunning =
      promptPreparation && node.preparationState === "running";
    const phase = preparationFailed
      ? "attention"
      : preparationRunning
      ? "running"
      : phaseOf(status);
    group.items.push({
      id: `graph:${node.id}`,
      source: "graph",
      node,
      label: creatorWorkNodeLabel(node, project),
      ...(projectedTask ? { task: projectedTask } : {}),
      status,
      statusLabel: outdatedCompose
        ? i18n.t("agentProgress.composeNeedsUpdate")
        : promptPreparation
        ? i18n.t(
            preparationFailed
              ? "r2v.sync.preparationFailed"
              : preparationRunning
              ? "r2v.sync.preparationRunning"
              : "r2v.sync.preparationWaiting",
          )
        : lastAttemptNeedsAttention
        ? i18n.t(
            task.status === "CANCELLED"
              ? "agentProgress.lastAttemptCancelled"
              : "agentProgress.lastAttemptFailed",
            {
              defaultValue:
                task.status === "CANCELLED"
                  ? "上次尝试已停止"
                  : "上次尝试未完成",
            },
          )
        : projectedTask
        ? creatorStatusLabel(projectedTask.status)
        : i18n.t(`agentActivity.${graphStates[node.status] ?? "currentStage"}`),
      phase,
      locator: operationLocator(
        node.kind,
        {
          ...locator,
          ...(tid ?? group.locator?.timelineId
            ? { timelineId: (tid ?? group.locator?.timelineId)! }
            : {}),
        },
        project,
        node.id,
      ),
      progressPercent: percent(
        projectedTask ? projectedTask.progress : node.progress,
        phase,
      ),
    });
  }
  // Supersession is explicit; relatedRunId identifies a parent and is not a replacement.
  const superseded = new Set(
    input.runs.map((run) => run.supersedesRunId).filter(Boolean),
  );
  const onlySnapshotTargets = (refs: string[]) =>
    refs.length > 0 &&
    refs.every(
      (ref) =>
        ref.startsWith("timeline:snapshot:") ||
        ref.startsWith("snapshot:") ||
        (ref.startsWith("element:") &&
          !timelineOf(ref) &&
          project &&
          Object.entries(project.timelines.items).some(
            ([id, timeline]) =>
              id.startsWith("snapshot:") &&
              timeline.elements_by_id?.[ref.slice(8)],
          )),
    );
  const runs = input.runs.filter(
    (run) =>
      !superseded.has(run.id) && !onlySnapshotTargets(run.targetRefs ?? []),
  );
  const visibleRunIds = new Set<string>();
  for (const run of runs) {
    const linkedTasks = tasks.filter(
      (task) =>
        task.specialistRunId === run.id || run.taskRefs?.includes(task.id),
    );
    if (
      !["RUNNING_MODEL", "WAITING_AUTHORIZATION", "BLOCKED"].includes(
        run.status,
      ) &&
      linkedTasks.length > 0 &&
      linkedTasks.every((task) => representedTasks.has(task.id))
    )
      continue;
    visibleRunIds.add(run.id);
    const group = groupFor(run.targetRefs ?? []);
    const phase = phaseOf(run.status);
    const targetLabels = [
      ...new Set(
        (run.targetRefs ?? []).map((ref) => creatorTargetLabel(ref, project)),
      ),
    ];
    group.items.push({
      id: `run:${run.id}`,
      source: "run",
      run,
      label: [
        creatorRoleLabel(run.role),
        ...targetLabels.filter((label) => label !== group.label),
      ].join(" · "),
      status: run.status,
      statusLabel: creatorStatusLabel(run.status),
      phase,
      locator: group.locator,
      progressPercent: null,
    });
  }
  for (const task of tasks) {
    if (!coreTasks.has(String(task.kind)) || representedTasks.has(task.id))
      continue;
    // A listed professional operation owns its explicitly linked supporting task.
    if (
      runs.some(
        (run) =>
          visibleRunIds.has(run.id) &&
          (task.specialistRunId === run.id || run.taskRefs?.includes(task.id)),
      )
    )
      continue;
    if (
      ["FAILED", "QUARANTINED"].includes(task.status) &&
      tasks.some(
        (other) =>
          other.id !== task.id &&
          other.kind === task.kind &&
          other.targetRef === task.targetRef &&
          other.status === "SUCCEEDED" &&
          isLater(other, task),
      )
    )
      continue;
    const tid = timelineOf(task.targetRef);
    if (task.targetRef.startsWith("timeline:") && !tid && project) continue;
    const locator: Record<string, string> | null = tid
      ? {
          page: "plan",
          timelineId: tid,
          ...(task.targetRef.startsWith("element:")
            ? { elementId: task.targetRef.slice(8) }
            : {}),
        }
      : sourceRef(task.targetRef)
      ? { page: "assets" }
      : null;
    const group = groupFor([task.targetRef], locator ?? undefined);
    const target = creatorTargetLabel(task.targetRef, project);
    const label =
      String(task.kind) === "script_draft"
        ? i18n.t("blueprint.scriptTitle")
        : taskKindLabel(task.kind);
    const phase = phaseOf(task.status);
    group.items.push({
      id: `task:${task.id}`,
      source: "task",
      task,
      label: target && target !== group.label ? `${label} · ${target}` : label,
      status: task.status,
      statusLabel: creatorStatusLabel(task.status),
      phase,
      locator: locator
        ? operationLocator(String(task.kind), locator, project)
        : null,
      progressPercent: percent(task.progress, phase),
    });
  }
  const result = [...groups.values()].filter((group) => group.items.length);
  for (const group of result) {
    group.items.sort((a, b) => phaseOrder[a.phase] - phaseOrder[b.phase]);
    group.counts = countsOf(group.items);
  }
  result.sort(
    (a, b) =>
      Math.min(...a.items.map((item) => phaseOrder[item.phase])) -
        Math.min(...b.items.map((item) => phaseOrder[item.phase])) ||
      (a.kind === "timeline"
        ? Math.max(0, displayTimelineIds.indexOf(a.locator?.timelineId ?? ""))
        : displayTimelineIds.length + 1) -
        (b.kind === "timeline"
          ? Math.max(0, displayTimelineIds.indexOf(b.locator?.timelineId ?? ""))
          : displayTimelineIds.length + 1),
  );
  return {
    groups: result,
    counts: countsOf(result.flatMap((group) => group.items)),
  };
}
