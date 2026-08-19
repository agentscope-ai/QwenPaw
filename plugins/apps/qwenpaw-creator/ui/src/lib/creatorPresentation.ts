import type {
  ProjectDocument,
  SpecialistRunStatus,
  TaskStatus,
  TaskView,
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

function elementName(
  project: ProjectDocument | null | undefined,
  elementId: string,
): string | null {
  if (!project) return null;
  for (const timeline of Object.values(project.timelines.items)) {
    const element = timeline.elements_by_id[elementId];
    if (element)
      return element.label || i18n.t("presentation.targets.timelineContent");
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
  if (ref.startsWith("timeline:"))
    return i18n.t("presentation.targets.mainTimeline");
  if (ref.startsWith("source:")) {
    const sourceId = ref.slice("source:".length);
    return (
      project?.sources.sources.items[sourceId]?.display_name ||
      i18n.t("presentation.targets.currentSource")
    );
  }
  if (ref.startsWith("asset:")) {
    const logicalAssetId = ref.slice("asset:".length);
    const entity = project?.visual?.entities?.items?.[logicalAssetId];
    if (entity?.name) return entity.name;
    return (
      Object.values(project?.assets.source_versions_by_id ?? {}).find(
        (version) => version.logical_asset_id === logicalAssetId,
      )?.name || i18n.t("presentation.targets.currentSource")
    );
  }
  if (ref.startsWith("visual-entity:")) {
    const entityId = ref.slice("visual-entity:".length);
    return (
      project?.visual?.entities?.items?.[entityId]?.name ||
      i18n.t("presentation.targets.visualSetting")
    );
  }
  if (ref.startsWith("asset-version:")) {
    return (
      project?.assets.source_versions_by_id[ref.slice("asset-version:".length)]
        ?.name || i18n.t("presentation.targets.sourceVersion")
    );
  }
  if (ref.startsWith("artifact-version:")) {
    return (
      project?.assets.artifact_versions_by_id[
        ref.slice("artifact-version:".length)
      ]?.name || i18n.t("presentation.targets.genResult")
    );
  }
  if (ref.startsWith("file:")) return i18n.t("presentation.targets.sourceFile");
  if (ref.startsWith("artifact:"))
    return i18n.t("presentation.targets.genResult");
  return i18n.t("presentation.targets.currentProject");
}

export function creatorToolLabel(name: string): string {
  const labels: Record<string, string> = {
    read_project: i18n.t("presentation.tools.read_project"),
    read_project_file: i18n.t("presentation.tools.read_project_file"),
    jq_project: i18n.t("presentation.tools.jq_project"),
    elements_at: i18n.t("presentation.tools.elements_at"),
    delegate_to_agent: i18n.t("presentation.tools.delegate_to_agent"),
    analyze_source_media: i18n.t("presentation.tools.analyze_source_media"),
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
  elements_at: "presentation.toolRunning.elements_at",
  ground_prompt_context: "presentation.toolRunning.ground_prompt_context",
  analyze_source_media: "presentation.toolRunning.analyze_source_media",
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
};

export function getToolRunningLabel(name: string): string | null {
  const key = TOOL_RUNNING_LABEL_KEYS[name];
  return key ? i18n.t(key) : null;
}

export function getRoleRunningLabel(name: string): string | null {
  const roleLabel = creatorRoleLabel(name);
  if (!roleLabel || roleLabel === i18n.t("presentation.productionAssistant"))
    return null;
  return i18n.t("presentation.roleRunningSuffix", { role: roleLabel });
}

export function getEstimatedDuration(toolName: string): string | null {
  const durations: Record<string, string> = {
    image_generation: i18n.t(
      "presentation.estimatedDurations.image_generation",
    ),
    r2v_generation: i18n.t("presentation.estimatedDurations.r2v_generation"),
    analyze_source_media: i18n.t(
      "presentation.estimatedDurations.analyze_source_media",
    ),
    ai_edit: i18n.t("presentation.estimatedDurations.ai_edit"),
    finalize_video: i18n.t("presentation.estimatedDurations.finalize_video"),
    plan: i18n.t("presentation.estimatedDurations.plan"),
    grep_search: i18n.t("presentation.estimatedDurations.grep_search"),
    glob_search: i18n.t("presentation.estimatedDurations.glob_search"),
    ast_search: i18n.t("presentation.estimatedDurations.ast_search"),
  };
  return durations[toolName] ?? null;
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
