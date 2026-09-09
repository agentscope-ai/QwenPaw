import type {
  ProjectDocument,
  RefSearchItem,
  SpecialistRunStatus,
  TaskStatus,
  TaskView,
  WorkGraphNode,
} from "@/contracts/creator";
import i18n from "@/i18n";

const TASK_KIND_LABEL_KEYS: Record<TaskView["kind"], string> = {
  asset_ingest: "presentation.taskKinds.asset_ingest",
  asset_import: "presentation.taskKinds.asset_import",
  source_intelligence: "presentation.taskKinds.source_intelligence",
  source_memory_build: "presentation.taskKinds.source_memory_build",
  image_generation: "presentation.taskKinds.image_generation",
  r2v_generation: "presentation.taskKinds.r2v_generation",
  ai_edit_plan: "presentation.taskKinds.ai_edit_plan",
  ai_edit_execute: "presentation.taskKinds.ai_edit_execute",
  compose: "presentation.taskKinds.compose",
};

export function taskKindLabel(kind: string): string {
  const key = TASK_KIND_LABEL_KEYS[kind as TaskView["kind"]];
  return key ? i18n.t(key) : i18n.t("presentation.taskExecution");
}

const STATUS_LABEL_KEYS: Record<string, string> = {
  IDLE: "presentation.statuses.IDLE",
  QUEUED: "presentation.statuses.QUEUED",
  QUEUED_CAPACITY: "presentation.statuses.QUEUED_CAPACITY",
  RUNNING: "presentation.statuses.RUNNING",
  RUNNING_MODEL: "presentation.statuses.RUNNING_MODEL",
  WAITING_RUNTIME: "presentation.statuses.WAITING_RUNTIME",
  WAITING_AUTHORIZATION: "presentation.statuses.WAITING_AUTHORIZATION",
  WAITING_USER_INPUT: "presentation.statuses.WAITING_USER_INPUT",
  WAITING_EXECUTION_AUTH: "presentation.statuses.WAITING_EXECUTION_AUTH",
  PENDING_REVIEW: "presentation.statuses.PENDING_REVIEW",
  RESUMING: "presentation.statuses.RESUMING",
  INTERRUPT_REQUESTED: "presentation.statuses.INTERRUPT_REQUESTED",
  INTERRUPTED: "presentation.statuses.INTERRUPTED",
  SUCCEEDED: "presentation.statuses.SUCCEEDED",
  BLOCKED: "presentation.statuses.BLOCKED",
  FAILED: "presentation.statuses.FAILED",
  STALE: "presentation.statuses.STALE",
  CANCELLED: "presentation.statuses.CANCELLED",
  QUARANTINED: "presentation.statuses.QUARANTINED",
  ERROR: "presentation.statuses.ERROR",
};

export function creatorStatusLabel(
  status: SpecialistRunStatus | TaskStatus | string | null | undefined,
): string {
  if (!status) return i18n.t("presentation.dash");
  const key = STATUS_LABEL_KEYS[status];
  return key ? i18n.t(key) : i18n.t("presentation.processing");
}

const CREATOR_REF_PATTERN =
  /visual-variant:[\w.:-]+@[\w.:-]+|(?:visual-entity|artifact-version|asset-version|cast-lineup|lineup|element|timeline|asset|source|artifact|file|project):[\w.-]+(?::[\w.-]+)*/gu;

/** Names are public metadata; ids and file-system paths are not name fallbacks. */
function publicName(value: unknown, ref: string): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const name = value.trim();
  const id = ref.slice(ref.indexOf(":") + 1);
  if (
    name === ref ||
    name === id ||
    /^(?:\/|~\/|[A-Za-z]:\\|(?:file|https?):\/\/|(?:[\w.-]+[\\/])+[\w.-]+$)/u.test(
      name,
    ) ||
    /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/iu.test(name) ||
    /^(?:\{\s*"|\[\s*\{)/u.test(name) ||
    /^(?:visual-variant|visual-entity|artifact-version|asset-version|cast-lineup|element|timeline|asset|source|artifact|file|project):/u.test(
      name,
    )
  )
    return null;
  return name;
}

function elementName(
  project: ProjectDocument | null | undefined,
  elementId: string,
): string | null {
  if (!project) return null;
  for (const timeline of Object.values(project.timelines?.items ?? {})) {
    const element = timeline.elements_by_id[elementId];
    if (element) return publicName(element.label, `element:${elementId}`);
  }
  return null;
}

export function creatorTargetLabel(
  ref: string,
  project?: ProjectDocument | null,
): string {
  if (!ref || ref === "project")
    return i18n.t("presentation.targets.currentProject");
  if (ref === "project:assets")
    return i18n.t("presentation.targets.assetsAndResults");
  if (ref === "project:plan") return i18n.t("presentation.targets.videoPlan");
  if (ref.startsWith("element:"))
    return (
      elementName(project, ref.slice("element:".length)) ??
      i18n.t("presentation.targets.timelineContent")
    );
  if (ref.startsWith("timeline:")) {
    const timeline =
      project?.timelines?.items?.[ref.slice("timeline:".length)] ??
      project?.timelines?.items?.[ref];
    return (
      publicName(timeline?.title, ref) ??
      publicName(timeline?.name, ref) ??
      i18n.t("presentation.targets.mainTimeline")
    );
  }
  if (ref.startsWith("source:")) {
    const sourceId = ref.slice("source:".length);
    return (
      publicName(
        project?.sources?.sources?.items?.[sourceId]?.display_name,
        ref,
      ) ?? i18n.t("presentation.targets.currentSource")
    );
  }
  if (ref.startsWith("asset:")) {
    const logicalAssetId = ref.slice("asset:".length);
    const entity = project?.visual?.entities?.items?.[logicalAssetId];
    const entityName = publicName(entity?.name, ref);
    if (entityName) return entityName;
    return (
      publicName(
        Object.values(project?.assets?.source_versions_by_id ?? {}).find(
          (version) => version.logical_asset_id === logicalAssetId,
        )?.name,
        ref,
      ) ?? i18n.t("presentation.targets.currentSource")
    );
  }
  if (ref.startsWith("visual-entity:")) {
    const entityId = ref.slice("visual-entity:".length);
    return (
      publicName(project?.visual?.entities?.items?.[entityId]?.name, ref) ??
      i18n.t("presentation.targets.visualSetting")
    );
  }
  if (ref.startsWith("visual-variant:")) {
    const identity = ref.slice("visual-variant:".length);
    const separator = identity.lastIndexOf("@");
    const entity =
      separator > 0
        ? project?.visual?.entities?.items?.[identity.slice(0, separator)]
        : undefined;
    const name = publicName(entity?.name, ref);
    if (!name) return i18n.t("presentation.targets.visualSetting");
    const variant = entity?.variants?.items?.[identity.slice(separator + 1)];
    if (!variant || (entity?.variants?.order?.length ?? 0) <= 1) return name;
    const description = publicName(variant.requirements, ref)
      ?.split(/[。！？\n]/u, 1)[0]
      ?.trim();
    return description
      ? `${name} · ${
          description.length > 24 ? `${description.slice(0, 24)}…` : description
        }`
      : name;
  }
  if (ref.startsWith("cast-lineup:") || ref.startsWith("lineup:")) {
    return (
      publicName(
        project?.visual?.cast_lineups?.items?.[ref.slice(ref.indexOf(":") + 1)]
          ?.name,
        ref,
      ) ?? i18n.t("presentation.targets.visualSetting")
    );
  }
  if (ref.startsWith("asset-version:")) {
    return (
      publicName(
        project?.assets?.source_versions_by_id?.[
          ref.slice("asset-version:".length)
        ]?.name,
        ref,
      ) ?? i18n.t("presentation.targets.sourceVersion")
    );
  }
  if (ref.startsWith("artifact-version:")) {
    return (
      publicName(
        project?.assets?.artifact_versions_by_id?.[
          ref.slice("artifact-version:".length)
        ]?.name,
        ref,
      ) ?? i18n.t("presentation.targets.genResult")
    );
  }
  if (ref.startsWith("file:")) return i18n.t("presentation.targets.sourceFile");
  if (ref.startsWith("artifact:"))
    return i18n.t("presentation.targets.genResult");
  return i18n.t("presentation.targets.currentProject");
}

/** One label policy for chips, search rows, accessible labels and tool targets. */
export function creatorReferenceLabel(
  item: Pick<RefSearchItem, "ref" | "name">,
  project?: ProjectDocument | null,
): string {
  const currentLabel = creatorTargetLabel(item.ref, project);
  if (project && currentLabel !== creatorTargetLabel(item.ref))
    return currentLabel;
  return publicName(item.name, item.ref) ?? currentLabel;
}

/** Display public names without making internal reference tokens into links. */
export function humanizeCreatorRefs(
  text: string,
  project?: ProjectDocument | null,
): string {
  // The model can mention a raw object id in prose or a Markdown table, without
  // the canonical reference prefix. Resolve only exact ids in this project.
  const knownIds = new Map<string, string>();
  for (const [id] of Object.entries(project?.visual?.entities?.items ?? {}))
    knownIds.set(id, creatorTargetLabel(`visual-entity:${id}`, project));
  for (const timeline of Object.values(project?.timelines?.items ?? {}))
    for (const [id] of Object.entries(timeline.elements_by_id ?? {}))
      knownIds.set(id, creatorTargetLabel(`element:${id}`, project));
  let fenced = false;
  const namedText = text
    .split("\n")
    .map((line) => {
      if (/^\s*```/u.test(line)) {
        fenced = !fenced;
        return line;
      }
      if (
        fenced ||
        /^\s*(?:\*\*)?(?:台词|对白|字幕|旁白|片名|标题|Dialogue|Caption|Narration|Title)(?:\*\*)?\s*[：:]/u.test(
          line,
        )
      )
        return line;
      return line.replace(
        /https?:\/\/[^\s)]+|《[^》]*》|“[^”]*”|`[^`\n]+`|[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)*/gu,
        (token) => {
          if (token.startsWith("`"))
            return knownIds.get(token.slice(1, -1)) ?? token;
          // Ordinary word ids are ambiguous with authored language.
          return /[:_-]/u.test(token) ? knownIds.get(token) ?? token : token;
        },
      );
    })
    .join("\n");
  const inlineReferences = namedText.replace(
    /`([^`\n]+)`/gu,
    (code, token: string) => {
      if (project) {
        const element = elementName(project, token);
        if (element) return element;
        if (project.timelines?.items?.[token])
          return creatorTargetLabel(`timeline:${token}`, project);
      }
      if (
        /^(?:visual-variant|visual-entity|artifact-version|asset-version|cast-lineup|lineup|element|timeline|asset|source|artifact|file|project):[^\s]+$/u.test(
          token,
        )
      )
        return creatorTargetLabel(token, project);
      if (/^seg:\d+(?:\.\d+)?-\d+(?:\.\d+)?$/u.test(token))
        return creatorTargetLabel(`element:${token}`, project);
      return code;
    },
  );
  const plainReferences = inlineReferences
    .replace(
      /\[[^\]\n]*\]\(((?:visual-variant|visual-entity|artifact-version|asset-version|cast-lineup|lineup|element|timeline|asset|source|artifact|file|project):[^\s)]+)\)/gu,
      (_match, ref: string) => creatorTargetLabel(ref, project),
    )
    .replace(/file:[^\s`"'<>，。！？,;)\]]+/gu, (ref) =>
      creatorTargetLabel(ref, project),
    );
  return plainReferences
    .replace(CREATOR_REF_PATTERN, (ref) => creatorTargetLabel(ref, project))
    .replace(/\bseg:\d+(?:\.\d+)?-\d+(?:\.\d+)?\b/gu, (id) =>
      creatorTargetLabel(`element:${id}`, project),
    );
}

/** Work graph labels are backend fallbacks, not guaranteed public names. */
export function creatorWorkNodeLabel(
  node: Pick<WorkGraphNode, "id" | "label" | "locator"> & {
    kind: string;
    timelineId?: string | null;
  },
  project?: ProjectDocument | null,
): string {
  const kindKeys: Record<string, string> = {
    visual: "workGraph.laneVisual",
    lineup: "workGraph.laneLineup",
    script: "blueprint.scriptTitle",
    storyboard: "presentation.outputs.storyboard",
    video: "presentation.taskKinds.r2v_generation",
    compose: "workGraph.laneCompose",
  };
  const kindLabel = i18n.t(kindKeys[node.kind] ?? "agentActivity.currentStage");
  const locator = node.locator ?? {};
  const timelineId = node.timelineId ?? locator.timelineId;
  const ref = locator.elementId
    ? `element:${locator.elementId}`
    : locator.assetId
    ? `visual-entity:${locator.assetId}`
    : node.kind === "lineup" && node.id.startsWith("lineup:")
    ? `cast-lineup:${node.id.slice("lineup:".length)}`
    : timelineId
    ? `timeline:${timelineId}`
    : (node.kind === "compose" || node.kind === "script") &&
      node.id.startsWith(`${node.kind}:`)
    ? `timeline:${node.id.slice(node.kind.length + 1)}`
    : "";
  if (ref && project) {
    const objectLabel = creatorTargetLabel(ref, project);
    if (objectLabel !== creatorTargetLabel(ref))
      return `${objectLabel} · ${kindLabel}`;
  }
  const internalIds = [
    node.id,
    ref.slice(ref.indexOf(":") + 1),
    timelineId,
    locator.elementId,
    locator.assetId,
  ].filter(Boolean);
  const label = publicName(node.label, ref || node.id);
  if (
    label &&
    !internalIds.some((id) => label.includes(id)) &&
    !/(?:\b(?:seg|timeline|element|lineup|visual|compose|script):|\b[a-f\d]{8}-[a-f\d-]{27,}\b)/iu.test(
      label,
    )
  )
    return label;
  return kindLabel;
}

// Only built-in guide names have a public title. External names can contain
// implementation details; never turn arbitrary tool arguments into UI copy.
const SKILL_GUIDE_KEYS = new Map([
  ["visual-asset-design", "visualDesign"],
  ["professional-media-prompts", "mediaPrompts"],
]);

function skillGuideKey(
  arguments_?: Record<string, unknown>,
): string | undefined {
  return typeof arguments_?.skill === "string"
    ? SKILL_GUIDE_KEYS.get(arguments_.skill)
    : undefined;
}

export function creatorToolLabel(
  name: string,
  arguments_?: Record<string, unknown>,
): string {
  const guide = name === "view_skill" ? skillGuideKey(arguments_) : undefined;
  if (guide) return i18n.t(`presentation.skillGuides.${guide}`);
  const labels: Record<string, string> = {
    read_project: i18n.t("presentation.tools.read_project"),
    read_project_file: i18n.t("presentation.tools.read_project_file"),
    jq_project: i18n.t("presentation.tools.jq_project"),
    patch_project: i18n.t("presentation.tools.jq_project"),
    request_workgraph_execution: i18n.t(
      "presentation.tools.request_workgraph_execution",
    ),
    elements_at: i18n.t("presentation.tools.elements_at"),
    delegate_to_agent: i18n.t("presentation.tools.delegate_to_agent"),
    analyze_source_media: i18n.t("presentation.tools.analyze_source_media"),
    read_source_video: i18n.t("presentation.tools.read_source_video", {
      defaultValue: i18n.t("presentation.tools.analyze_source_media"),
    }),
    observe_source_clip: i18n.t("presentation.tools.observe_source_clip", {
      defaultValue: i18n.t("presentation.tools.analyze_source_media"),
    }),
    check_observation_tasks: i18n.t(
      "presentation.tools.check_observation_tasks",
      { defaultValue: i18n.t("presentation.tools.analyze_source_media") },
    ),
    review_scene: i18n.t("presentation.tools.review_scene", {
      defaultValue: i18n.t("presentation.tools.complete_current_change"),
    }),
    source_intelligence: i18n.t("presentation.tools.source_intelligence"),
    ai_edit: i18n.t("presentation.tools.ai_edit"),
    r2v_generation: i18n.t("presentation.tools.r2v_generation"),
    image_generation: i18n.t("presentation.tools.image_generation"),
    read_file: i18n.t("presentation.tools.read_file"),
    write_file: i18n.t("presentation.tools.write_file"),
    edit_file: i18n.t("presentation.tools.edit_file"),
    append_file: i18n.t("presentation.tools.append_file"),
    grep_search: i18n.t("presentation.tools.grep_search"),
    glob_search: i18n.t("presentation.tools.glob_search"),
    ast_search: i18n.t("presentation.tools.ast_search"),
    plan: i18n.t("presentation.tools.plan"),
    final: i18n.t("presentation.tools.final"),
    finalize_video: i18n.t("presentation.tools.finalize_video"),
    yield_until_runtime_event: i18n.t(
      "presentation.tools.yield_until_runtime_event",
    ),
    complete_current_change: i18n.t(
      "presentation.tools.complete_current_change",
    ),
    ground_prompt_context: i18n.t("presentation.tools.ground_prompt_context"),
    transcribe_source_audio: i18n.t(
      "presentation.tools.transcribe_source_audio",
    ),
    commit_source_intelligence: i18n.t(
      "presentation.tools.commit_source_intelligence",
    ),
    s2v_generation: i18n.t("presentation.tools.s2v_generation"),
    tts_generation: i18n.t("presentation.tools.tts_generation"),
    create_character_voice: i18n.t("presentation.tools.create_character_voice"),
    read_document: i18n.t("presentation.tools.read_document"),
    query_source_memory: i18n.t("presentation.tools.query_source_memory"),
    design_motion_overlays: i18n.t("presentation.tools.design_motion_overlays"),
    view_skill: i18n.t("presentation.tools.view_skill"),
    ground_image_objects: i18n.t("presentation.tools.ground_image_objects"),
    browser_use: i18n.t("presentation.tools.browser_use"),
    computer_use: i18n.t("presentation.tools.computer_use"),
  };
  return labels[name] ?? i18n.t("presentation.unknownTool");
}

export function creatorRoleLabel(name: string): string {
  const labels: Record<string, string> = {
    source_intelligence_agent: i18n.t(
      "presentation.roles.source_intelligence_agent",
    ),
    visual_development_agent: i18n.t(
      "presentation.roles.visual_development_agent",
    ),
    v_generation_director: i18n.t("presentation.roles.v_generation_director"),
    ai_editing_director: i18n.t("presentation.roles.ai_editing_director"),
    r2v_generation_director: i18n.t(
      "presentation.roles.r2v_generation_director",
    ),
    story_planning_agent: i18n.t("presentation.roles.story_planning_agent"),
    unit_planning_routing_agent: i18n.t(
      "presentation.roles.unit_planning_routing_agent",
    ),
    review_consistency_agent: i18n.t(
      "presentation.roles.review_consistency_agent",
    ),
  };
  return labels[name] ?? i18n.t("presentation.specialistProduction");
}

const TOOL_RUNNING_LABEL_KEYS: Record<string, string> = {
  read_project: "presentation.toolRunning.read_project",
  read_project_file: "presentation.toolRunning.read_project_file",
  jq_project: "presentation.toolRunning.jq_project",
  patch_project: "presentation.toolRunning.jq_project",
  request_workgraph_execution:
    "presentation.toolRunning.request_workgraph_execution",
  elements_at: "presentation.toolRunning.elements_at",
  ground_prompt_context: "presentation.toolRunning.ground_prompt_context",
  analyze_source_media: "presentation.toolRunning.analyze_source_media",
  read_source_video: "presentation.toolRunning.read_source_video",
  observe_source_clip: "presentation.toolRunning.observe_source_clip",
  check_observation_tasks: "presentation.toolRunning.check_observation_tasks",
  review_scene: "presentation.toolRunning.review_scene",
  source_intelligence: "presentation.toolRunning.source_intelligence",
  transcribe_source_audio: "presentation.toolRunning.transcribe_source_audio",
  commit_source_intelligence:
    "presentation.toolRunning.commit_source_intelligence",
  read_document: "presentation.toolRunning.read_document",
  query_source_memory: "presentation.toolRunning.query_source_memory",
  tts_generation: "presentation.toolRunning.tts_generation",
  create_character_voice: "presentation.toolRunning.create_character_voice",
  s2v_generation: "presentation.toolRunning.s2v_generation",
  design_motion_overlays: "presentation.toolRunning.design_motion_overlays",
  ai_edit: "presentation.toolRunning.ai_edit",
  read_file: "presentation.toolRunning.read_file",
  write_file: "presentation.toolRunning.write_file",
  edit_file: "presentation.toolRunning.edit_file",
  append_file: "presentation.toolRunning.append_file",
  grep_search: "presentation.toolRunning.grep_search",
  glob_search: "presentation.toolRunning.glob_search",
  ast_search: "presentation.toolRunning.ast_search",
  plan: "presentation.toolRunning.plan",
  final: "presentation.toolRunning.final",
  finalize_video: "presentation.toolRunning.finalize_video",
  yield_until_runtime_event:
    "presentation.toolRunning.yield_until_runtime_event",
  complete_current_change: "presentation.toolRunning.complete_current_change",
  view_skill: "presentation.toolRunning.view_skill",
  ground_image_objects: "presentation.toolRunning.ground_image_objects",
  browser_use: "presentation.toolRunning.browser_use",
  computer_use: "presentation.toolRunning.computer_use",
};

export function getToolRunningLabel(
  name: string,
  arguments_?: Record<string, unknown>,
): string | null {
  const guide = name === "view_skill" ? skillGuideKey(arguments_) : undefined;
  if (guide) return i18n.t(`presentation.skillGuidesRunning.${guide}`);
  const key = TOOL_RUNNING_LABEL_KEYS[name];
  return key ? i18n.t(key) : null;
}

export function getRoleRunningLabel(name: string): string | null {
  const roleLabel = creatorRoleLabel(name);
  if (!roleLabel || roleLabel === i18n.t("presentation.productionAssistant"))
    return null;
  return i18n.t("presentation.roleRunningSuffix", { role: roleLabel });
}

/** @deprecated There is no backend duration estimate; use actual elapsed time. */
export function getEstimatedDuration(_toolName: string): null {
  return null;
}

export function creatorEventLabel(type: string): string {
  const labels: Record<string, string> = {
    "workspace.project_committed": i18n.t(
      "presentation.events.workspace.project_committed",
    ),
    "workspace.project_changed": i18n.t(
      "presentation.events.workspace.project_changed",
    ),
    "review.created": i18n.t("presentation.events.review.created"),
    "review.applied": i18n.t("presentation.events.review.applied"),
    "review.resolved": i18n.t("presentation.events.review.resolved"),
    "task.queued": i18n.t("presentation.events.task.queued"),
    "task.started": i18n.t("presentation.events.task.started"),
    "task.completed": i18n.t("presentation.events.task.completed"),
    "task.failed": i18n.t("presentation.events.task.failed"),
  };
  if (labels[type]) return labels[type];
  if (type.startsWith("workspace."))
    return i18n.t("presentation.eventFallbacks.workspace");
  if (type.startsWith("review."))
    return i18n.t("presentation.eventFallbacks.review");
  if (type.startsWith("task."))
    return i18n.t("presentation.eventFallbacks.task");
  return i18n.t("presentation.projectActivity");
}

export function outputLabel(name: string): string {
  const labels: Record<string, string> = {
    storyboard: i18n.t("presentation.outputs.storyboard"),
    main: i18n.t("presentation.outputs.main"),
    overlay: i18n.t("presentation.outputs.overlay"),
    render: i18n.t("presentation.outputs.render"),
    audio: i18n.t("presentation.outputs.audio"),
  };
  return labels[name] ?? i18n.t("presentation.genResult");
}
