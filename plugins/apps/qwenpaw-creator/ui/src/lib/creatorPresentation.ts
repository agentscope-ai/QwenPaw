import type {
  ProjectDocument,
  SpecialistRunStatus,
  TaskStatus,
  TaskView,
} from "@/contracts/creator";

const TASK_KIND_LABELS: Record<TaskView["kind"], string> = {
  asset_ingest: "素材入库",
  asset_import: "素材导入",
  source_intelligence: "素材理解",
  image_generation: "画面生成",
  r2v_generation: "视频生成",
  ai_edit_plan: "剪辑规划",
  ai_edit_execute: "剪辑合成",
  compose: "成片合成",
};

export function taskKindLabel(kind: string): string {
  return TASK_KIND_LABELS[kind as TaskView["kind"]] ?? "任务执行";
}

const STATUS_LABELS: Record<string, string> = {
  IDLE: "待命",
  QUEUED: "等待中",
  QUEUED_CAPACITY: "排队等待资源",
  RUNNING: "处理中",
  RUNNING_MODEL: "正在构思",
  WAITING_RUNTIME: "等待制作结果",
  WAITING_AUTHORIZATION: "等待确认",
  WAITING_USER_INPUT: "等待补充信息",
  WAITING_EXECUTION_AUTH: "等待执行确认",
  PENDING_REVIEW: "等待审阅",
  RESUMING: "继续处理中",
  INTERRUPT_REQUESTED: "正在停止",
  SUCCEEDED: "已完成",
  BLOCKED: "需要处理",
  FAILED: "失败",
  STALE: "已被新版本替换",
  CANCELLED: "已取消",
  QUARANTINED: "需要复核",
  ERROR: "发生错误",
};

export function creatorStatusLabel(
  status: SpecialistRunStatus | TaskStatus | string | null | undefined,
): string {
  return status ? STATUS_LABELS[status] ?? "处理中" : "—";
}

function elementName(
  project: ProjectDocument | null | undefined,
  elementId: string,
): string | null {
  if (!project) return null;
  for (const timeline of Object.values(project.timelines.items)) {
    const element = timeline.elements_by_id[elementId];
    if (element) return element.label || "时间线内容";
  }
  return null;
}

export function creatorTargetLabel(
  ref: string,
  project?: ProjectDocument | null,
): string {
  if (!ref || ref === "project") return "当前项目";
  if (ref === "project:assets") return "素材与生成结果";
  if (ref === "project:plan") return "视频方案";
  if (ref.startsWith("element:"))
    return elementName(project, ref.slice("element:".length)) ?? "时间线内容";
  if (ref.startsWith("timeline:")) return "主时间轴";
  if (ref.startsWith("source:")) {
    const sourceId = ref.slice("source:".length);
    return project?.sources.sources.items[sourceId]?.display_name || "当前素材";
  }
  if (ref.startsWith("asset:")) {
    const logicalAssetId = ref.slice("asset:".length);
    // For visual entities (scene/character/prop), resolve asset:xxx targets
    // to the entity's real name first, so users never see codes like
    // asset:char:fox.
    const entity = project?.visual?.entities?.items?.[logicalAssetId];
    if (entity?.name) return entity.name;
    return (
      Object.values(project?.assets.source_versions_by_id ?? {}).find(
        (version) => version.logical_asset_id === logicalAssetId,
      )?.name || "当前素材"
    );
  }
  if (ref.startsWith("visual-entity:")) {
    const entityId = ref.slice("visual-entity:".length);
    return project?.visual?.entities?.items?.[entityId]?.name || "视觉设定";
  }
  if (ref.startsWith("asset-version:")) {
    return (
      project?.assets.source_versions_by_id[ref.slice("asset-version:".length)]
        ?.name || "素材版本"
    );
  }
  if (ref.startsWith("artifact-version:")) {
    return (
      project?.assets.artifact_versions_by_id[
        ref.slice("artifact-version:".length)
      ]?.name || "生成结果"
    );
  }
  if (ref.startsWith("file:")) return "素材文件";
  if (ref.startsWith("artifact:")) return "生成结果";
  return "当前项目";
}

export function creatorToolLabel(name: string): string {
  const labels: Record<string, string> = {
    read_project: "查看视频方案",
    read_project_file: "读取素材分析",
    jq_project: "更新视频方案",
    elements_at: "查看当前时间点",
    delegate_to_agent: "安排专业制作",
    analyze_source_media: "理解素材",
    source_intelligence: "理解素材",
    ai_edit: "执行剪辑",
    r2v_generation: "生成视频",
    image_generation: "生成画面",
    read_file: "读取文件",
    write_file: "写入文件",
    edit_file: "编辑文件",
    append_file: "追加内容",
    grep_search: "搜索内容",
    glob_search: "搜索文件",
    ast_search: "搜索代码结构",
    plan: "制定计划",
    final: "整理回复",
    finalize_video: "合成视频",
    yield_until_runtime_event: "等待执行",
    complete_current_change: "完成检查",
    ground_prompt_context: "核对画面上下文",
    transcribe_source_audio: "音频转写",
    commit_source_intelligence: "写入理解结果",
  };
  return labels[name] ?? "处理中";
}

export function creatorRoleLabel(name: string): string {
  const labels: Record<string, string> = {
    source_intelligence_agent: "素材理解",
    visual_development_agent: "视觉开发",
    v_generation_director: "视频制作",
    ai_editing_director: "剪辑制作",
    r2v_generation_director: "视频制作",
    story_planning_agent: "规划故事",
    unit_planning_routing_agent: "规划单元",
    review_consistency_agent: "一致性检查",
  };
  return labels[name] ?? "专业制作";
}

const TOOL_RUNNING_LABELS: Record<string, string> = {
  read_project: "正在查看项目…",
  read_project_file: "正在阅读素材分析…",
  jq_project: "正在修改项目…",
  elements_at: "正在查看时间轴…",
  ground_prompt_context: "正在核对画面上下文…",
  analyze_source_media: "素材理解中…",
  source_intelligence: "素材理解中…",
  transcribe_source_audio: "素材音频转写中…",
  commit_source_intelligence: "素材理解写入中…",
  ai_edit: "剪辑执行中…",
  read_file: "正在读取文件…",
  write_file: "正在写入文件…",
  edit_file: "正在编辑文件…",
  append_file: "正在追加内容…",
  grep_search: "正在搜索内容…",
  glob_search: "正在搜索文件…",
  ast_search: "正在搜索代码结构…",
  plan: "正在制定计划…",
  final: "正在整理回复…",
  finalize_video: "正在合成视频…",
  yield_until_runtime_event: "等待执行中…",
  complete_current_change: "正在完成检查…",
};

export function getToolRunningLabel(name: string): string | null {
  return TOOL_RUNNING_LABELS[name] ?? null;
}

export function getRoleRunningLabel(name: string): string | null {
  const roleLabel = creatorRoleLabel(name);
  if (!roleLabel || roleLabel === "制作助手") return null;
  return `${roleLabel}中`;
}

export function getEstimatedDuration(toolName: string): string | null {
  const durations: Record<string, string> = {
    image_generation: "预计 30-60 秒",
    r2v_generation: "预计 2-5 分钟",
    analyze_source_media: "预计 10-30 秒",
    ai_edit: "预计 30-60 秒",
    finalize_video: "预计 1-3 分钟",
    plan: "预计 5-15 秒",
    grep_search: "预计 1-5 秒",
    glob_search: "预计 1-5 秒",
    ast_search: "预计 1-5 秒",
  };
  return durations[toolName] ?? null;
}

export function creatorEventLabel(type: string): string {
  const labels: Record<string, string> = {
    "workspace.project_committed": "视频方案已更新",
    "workspace.project_changed": "视频方案已更新",
    "review.created": "已生成待审改动",
    "review.applied": "改动已应用",
    "review.resolved": "审阅已完成",
    "task.queued": "制作任务已排队",
    "task.started": "制作任务已开始",
    "task.completed": "制作任务已完成",
    "task.failed": "制作任务失败",
  };
  if (labels[type]) return labels[type];
  if (type.startsWith("workspace.")) return "视频方案已更新";
  if (type.startsWith("review.")) return "审阅状态已更新";
  if (type.startsWith("task.")) return "制作状态已更新";
  return "项目动态";
}

export function outputLabel(name: string): string {
  const labels: Record<string, string> = {
    storyboard: "分镜图",
    main: "主画面",
    overlay: "字幕与动效",
    render: "成片",
    audio: "音频",
  };
  return labels[name] ?? "生成结果";
}
