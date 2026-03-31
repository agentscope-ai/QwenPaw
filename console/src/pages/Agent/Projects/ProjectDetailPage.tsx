import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MinusOutlined,
  PlusOutlined,
  SendOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Switch,
  Spin,
  Tag,
  Tabs,
  Typography,
  Upload,
  message,
} from "antd";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import { chatApi } from "../../../api/modules/chat";
import AnywhereChat from "../../../components/AnywhereChat";
import type { ChatSpec } from "../../../api/types/chat";
import type {
  AgentProjectSummary,
  AgentProjectFileInfo,
  ProjectPipelineArtifactRecord,
  ProjectPipelineRunDetail,
  ProjectPipelineRunSummary,
  ProjectPipelineTemplateInfo,
  PlatformFlowTemplateInfo,
  AgentSummary,
} from "../../../api/types/agents";
import { useAgentStore } from "../../../stores/agentStore";
import styles from "./index.module.less";

const { Title, Text } = Typography;
const { Dragger } = Upload;

function getCurrentAgent(
  agents: AgentSummary[],
  selectedAgent: string,
): AgentSummary | undefined {
  return agents.find((agent) => agent.id === selectedAgent);
}

function projectDirNameFromMetadata(metadataFile: string): string {
  const normalized = metadataFile.replace(/\\/g, "/").trim();
  if (!normalized) {
    return "";
  }
  const segments = normalized.split("/").filter(Boolean);
  return segments.length >= 2 ? segments[segments.length - 2] : "";
}

function buildProjectIdCandidates(project?: AgentProjectSummary): string[] {
  if (!project) {
    return [];
  }
  const candidates = [project.id, projectDirNameFromMetadata(project.metadata_file)]
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(candidates));
}

function matchesRouteProject(project: AgentProjectSummary, routeProjectId: string): boolean {
  return buildProjectIdCandidates(project).includes(routeProjectId);
}

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function isPreviewablePath(path: string): boolean {
  if (!path) {
    return false;
  }
  const normalized = path.replace(/\\/g, "/");
  if (normalized.startsWith(".")) {
    return false;
  }
  if (normalized.split("/").some((part) => part.startsWith("."))) {
    return false;
  }
  return true;
}

function statusTagColor(status: string): string {
  switch (status) {
    case "running":
      return "processing";
    case "succeeded":
      return "success";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "pending":
      return "default";
    default:
      return "blue";
  }
}

function formatRunTimeLabel(raw: string): string {
  if (!raw) {
    return "-";
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return raw;
  }
  const y = parsed.getFullYear();
  const m = String(parsed.getMonth() + 1).padStart(2, "0");
  const d = String(parsed.getDate()).padStart(2, "0");
  const hh = String(parsed.getHours()).padStart(2, "0");
  const mm = String(parsed.getMinutes()).padStart(2, "0");
  const ss = String(parsed.getSeconds()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
}

function sortChatsForRestore<T extends ChatSpec>(chats: T[]): T[] {
  const toMillis = (chat: ChatSpec): number => {
    const updatedTs = chat.updated_at ? Date.parse(chat.updated_at) : 0;
    if (Number.isFinite(updatedTs) && updatedTs > 0) {
      return updatedTs;
    }
    const createdTs = chat.created_at ? Date.parse(chat.created_at) : 0;
    return Number.isFinite(createdTs) ? createdTs : 0;
  };

  return [...chats].sort((a, b) => {
    const aRunning = a.status === "running";
    const bRunning = b.status === "running";
    if (aRunning !== bRunning) {
      // Prefer non-running chats to avoid restoring into empty-running sessions.
      return aRunning ? 1 : -1;
    }
    return toMillis(b) - toMillis(a);
  });
}

function buildProjectFlowWorkspaceRelativePath(projectId: string): string {
  return `projects/${projectId}/pipelines`;
}

function buildProjectFlowMemoryRelativePath(projectId: string): string {
  return `${buildProjectFlowWorkspaceRelativePath(projectId)}/flow-memory.md`;
}

function buildProjectFlowBindingKey(params: { projectId: string; templateId: string }): string {
  return `project-flow-design:${params.projectId}:${params.templateId || "draft"}`;
}

function getMetaString(meta: Record<string, unknown> | undefined, key: string): string {
  const value = meta?.[key];
  return typeof value === "string" ? value : "";
}

function isTextSourcePath(path: string): boolean {
  const normalized = path.toLowerCase();
  return (
    normalized.endsWith(".md") ||
    normalized.endsWith(".markdown") ||
    normalized.endsWith(".mdx") ||
    normalized.endsWith(".txt")
  );
}

function selectSeedSourceFiles(paths: string[]): string[] {
  const unique = Array.from(new Set(paths.map((item) => item.trim()).filter(Boolean)));
  const textFiles = unique.filter((item) => isTextSourcePath(item));
  const fallback = textFiles.length > 0 ? textFiles : unique;
  const prioritized = [...fallback].sort((a, b) => {
    const aPriority = a.includes("/data/") || a.includes("/raw/") ? 0 : 1;
    const bPriority = b.includes("/data/") || b.includes("/raw/") ? 0 : 1;
    if (aPriority !== bPriority) {
      return aPriority - bPriority;
    }
    return a.localeCompare(b);
  });
  return prioritized.slice(0, 4);
}

function buildProjectFlowBootstrapPrompt(params: {
  projectName: string;
  selectedTemplateName: string;
  flowMemoryPath: string;
  workspaceDir: string;
  sourceFiles: string[];
}): string {
  const seedFiles = selectSeedSourceFiles(params.sourceFiles);
  const fileLines = seedFiles.length
    ? seedFiles.map((file, index) => `${index + 1}. ${file}`).join("\n")
    : "- (source files will be uploaded next)";
  const shortageHint = seedFiles.length < 4
    ? `注意：当前仅检测到 ${seedFiles.length} 个候选源文件，请先按现有文件生成草案，并显式标注缺失输入。`
    : "";
  return [
    `你现在处于项目流程设计模式。项目：${params.projectName}`,
    `当前模板：${params.selectedTemplateName}`,
    `路径基准（workspace root）：${params.workspaceDir}`,
    "路径解析规则：以下 source files 与 flow memory path 均为相对路径，必须以 workspace root 为起点拼接后访问。",
    `flow memory path: ${params.flowMemoryPath}`,
    "请基于以下 4 个真实源文件，先给出可执行的 4~6 步流程草案，并为每步明确：inputs / outputs / depends_on / retry_policy。",
    "源文件列表：",
    fileLines,
    shortageHint,
    "输出要求：",
    "1) 先给流程总览；",
    "2) 再逐步给出结构化字段；",
    "3) 明确哪些是 source artifact、哪些是 intermediate、哪些是 final。",
  ].join("\n");
}

function inferMimeTypeByPath(path: string): string {
  const normalized = path.toLowerCase();
  if (normalized.endsWith(".md") || normalized.endsWith(".markdown") || normalized.endsWith(".mdx")) {
    return "text/markdown";
  }
  if (normalized.endsWith(".txt")) {
    return "text/plain";
  }
  if (normalized.endsWith(".json")) {
    return "application/json";
  }
  return "text/plain";
}

function isBuiltInProjectFile(path: string): boolean {
  const normalized = path.replace(/\\/g, "/").toLowerCase();
  const fileName = normalized.split("/").pop() || "";
  if (fileName === "project.md" || fileName === "heartbeat.md") {
    return true;
  }
  return false;
}

function buildAutoAttachAnalysisPrompt(params: {
  projectName: string;
  fileNames: string[];
  selectedRunId?: string;
}): string {
  const fileList = params.fileNames
    .slice(0, 8)
    .map((name, index) => `${index + 1}. ${name}`)
    .join("\n");
  const modeHint = params.selectedRunId
    ? "这些文件与当前运行上下文相关。"
    : "这些文件与当前项目设计上下文相关。";
  return [
    `我刚刚附加了 ${params.fileNames.length} 个项目文件，请合并分析。`,
    `项目：${params.projectName}`,
    modeHint,
    "文件列表：",
    fileList,
    "请先根据文件名和内容猜测我最可能的目标或需求，再用 2-4 条要点总结你的判断和建议下一步。",
    "如果信息不足，最后只补一个简短澄清问题；如果已经足够，就直接继续分析。",
  ].join("\n");
}

function buildAttachDraftPrompt(params: {
  projectName: string;
  selectedRunId?: string;
  selectedFiles: Array<{ path: string; size: number }>;
}): string {
  const modeHint = params.selectedRunId
    ? `当前运行：${params.selectedRunId}`
    : "当前上下文：流程设计";
  const fileList = params.selectedFiles
    .map((item, index) => `${index + 1}. ${item.path} (${item.size} bytes)`)
    .join("\n");
  return [
    `我已选择 ${params.selectedFiles.length} 个项目文件作为上下文。`,
    `项目：${params.projectName}`,
    modeHint,
    "文件列表：",
    fileList,
  ].join("\n");
}

function isSucceededStatus(status: string): boolean {
  return status === "succeeded" || status === "completed";
}

function toTimestamp(raw?: string): number {
  if (!raw) {
    return 0;
  }
  const ts = Date.parse(raw);
  return Number.isFinite(ts) ? ts : 0;
}

function buildImplementationAdvancePrompt(params: {
  projectName: string;
  templateName: string;
  templateId: string;
  runCount: number;
  latestRunStatus: string;
  gateSummary: string;
}): string {
  return [
    `我们继续以“对话驱动”方式推进项目流程构建。项目：${params.projectName}`,
    `当前流程：${params.templateName} (${params.templateId})`,
    `当前运行数：${params.runCount}，最近一次运行状态：${params.latestRunStatus || "none"}`,
    `验证门槛现状：${params.gateSummary}`,
    "请你输出下一轮实施计划（不是最终模板），要求：",
    "1) 仅调整最小必要步骤；",
    "2) 对每一步明确 inputs / outputs / depends_on / retry_policy；",
    "3) 说明本轮要验证的假设与成功判定；",
    "4) 最后给出‘我下一步该点击什么（Run / Attach / 继续对话）’。",
  ].join("\n");
}

function buildValidationRoundPrompt(params: {
  projectName: string;
  runId: string;
  templateName: string;
  gateSummary: string;
}): string {
  return [
    `请基于当前运行做一次“验证导向”复盘。项目：${params.projectName}`,
    `运行：${params.runId}，流程：${params.templateName}`,
    `当前门槛状态：${params.gateSummary}`,
    "请输出：",
    "1) 通过项 / 失败项（逐步列出）；",
    "2) 每个失败项的最小修复动作；",
    "3) 是否建议立即重跑；若是，给出重跑前必须修改的项；",
    "4) 用一句话判断：是否已到‘可吸收为模板’时机。",
  ].join("\n");
}

function buildPromotionDraftPrompt(params: {
  projectName: string;
  templateName: string;
  templateId: string;
  runId: string;
}): string {
  return [
    `我们准备把已验证成果吸收为模板草案。项目：${params.projectName}`,
    `目标模板：${params.templateName} (${params.templateId})，依据运行：${params.runId}`,
    "请输出结构化模板草案（不是解释文），要求：",
    "1) 仅保留已验证通过的步骤；",
    "2) 每步必须含 id/name/kind/inputs/outputs/depends_on/input_bindings/retry_policy；",
    "3) 标注本次吸收剔除的步骤及原因；",
    "4) 最后给一段简短变更摘要，便于我人工确认后保存。",
  ].join("\n");
}

const INLINE_FULL_MAX_BYTES = 32 * 1024;
const INLINE_TRUNCATE_MAX_BYTES = 256 * 1024;
const INLINE_TRUNCATE_HEAD_CHARS = 8000;
const INLINE_TRUNCATE_TAIL_CHARS = 4000;
const INLINE_TOTAL_CHAR_BUDGET = 20000;

export default function ProjectDetailPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { projectId } = useParams<{ projectId?: string }>();
  const { selectedAgent, agents, setAgents } = useAgentStore();
  const routeProjectId = useMemo(
    () => (projectId ? decodeURIComponent(projectId) : ""),
    [projectId],
  );

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [resolvedProjectRequestId, setResolvedProjectRequestId] = useState("");
  const [projectFiles, setProjectFiles] = useState<AgentProjectFileInfo[]>([]);
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [hideBuiltInFiles, setHideBuiltInFiles] = useState(true);
  const [fileContent, setFileContent] = useState("");
  const [filesLoading, setFilesLoading] = useState(false);
  const [contentLoading, setContentLoading] = useState(false);

  const [pipelineTemplates, setPipelineTemplates] = useState<
    ProjectPipelineTemplateInfo[]
  >([]);
  const [pipelineRuns, setPipelineRuns] = useState<ProjectPipelineRunSummary[]>(
    [],
  );
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState<ProjectPipelineRunDetail | null>(
    null,
  );
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [createRunLoading, setCreateRunLoading] = useState(false);
  const [platformTemplates, setPlatformTemplates] = useState<PlatformFlowTemplateInfo[]>([]);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [selectedPlatformTemplateId, setSelectedPlatformTemplateId] = useState("");
  const [runFocusChatId, setRunFocusChatId] = useState("");
  const [designFocusChatId, setDesignFocusChatId] = useState("");
  const [chatStarting, setChatStarting] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState("");
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [deletingProject, setDeletingProject] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<File[]>([]);
  const [uploadTargetDir, setUploadTargetDir] = useState("data");
  const [autoAttachRequest, setAutoAttachRequest] = useState<{
    id: string;
    mode?: "submit" | "draft";
    fileName?: string;
    content?: string;
    mimeType?: string;
    files?: Array<{
      fileName: string;
      content: string;
      mimeType?: string;
    }>;
    note?: string;
  } | null>(null);
  const [selectedAttachPaths, setSelectedAttachPaths] = useState<string[]>([]);
  const [sendingSelectedFiles, setSendingSelectedFiles] = useState(false);
  const [autoAnalyzeOnAttach, setAutoAnalyzeOnAttach] = useState(true);
  const runFocusChatIdRef = useRef("");
  const designFocusChatIdRef = useRef("");
  const designRestoreAttemptKeyRef = useRef("");
  const runRestoreAttemptKeyRef = useRef("");

  const currentAgent = useMemo(
    () => getCurrentAgent(agents, selectedAgent),
    [agents, selectedAgent],
  );

  const projects = useMemo(
    () => currentAgent?.projects ?? [],
    [currentAgent?.projects],
  );

  const selectedProject = useMemo(
    () => projects.find((project) => matchesRouteProject(project, routeProjectId)),
    [projects, routeProjectId],
  );

  const leaveConfirmText = useMemo(
    () =>
      t(
        "projects.leaveConfirm",
        "你有可能误触跳转。确定要离开当前项目页面吗？",
      ),
    [t],
  );

  const shouldBlockLeave = useMemo(() => {
    const runInProgress = runDetail?.status === "running" || runDetail?.status === "pending";
    const designSessionActive = Boolean(designFocusChatId && !selectedRunId);

    return Boolean(
      selectedAttachPaths.length > 0 ||
      pendingUploads.length > 0 ||
      uploadModalOpen ||
      importModalOpen ||
      sendingSelectedFiles ||
      uploadingFiles ||
      chatStarting ||
      createRunLoading ||
      runInProgress ||
      designSessionActive,
    );
  }, [
    chatStarting,
    createRunLoading,
    designFocusChatId,
    importModalOpen,
    pendingUploads.length,
    runDetail?.status,
    selectedAttachPaths.length,
    selectedRunId,
    sendingSelectedFiles,
    uploadModalOpen,
    uploadingFiles,
  ]);

  useEffect(() => {
    if (!shouldBlockLeave) {
      return;
    }

    const rawPushState = window.history.pushState.bind(window.history);
    const rawReplaceState = window.history.replaceState.bind(window.history);
    const rawGo = window.history.go.bind(window.history);
    const rawBack = window.history.back.bind(window.history);
    const rawForward = window.history.forward.bind(window.history);

    const shouldConfirmLeave = (nextUrl?: string | URL | null): boolean => {
      if (!nextUrl) {
        return false;
      }
      const current = new URL(window.location.href);
      const target = new URL(String(nextUrl), window.location.origin);
      return target.pathname !== current.pathname;
    };

    const confirmLeave = (): boolean => window.confirm(leaveConfirmText);

    const patchedPushState: History["pushState"] = function patched(
      data,
      unused,
      url,
    ) {
      if (shouldConfirmLeave(url) && !confirmLeave()) {
        return;
      }
      rawPushState(data, unused, url);
    };

    const patchedReplaceState: History["replaceState"] = function patched(
      data,
      unused,
      url,
    ) {
      if (shouldConfirmLeave(url) && !confirmLeave()) {
        return;
      }
      rawReplaceState(data, unused, url);
    };

    const patchedGo: History["go"] = function patched(delta) {
      if ((delta || 0) !== 0 && !confirmLeave()) {
        return;
      }
      rawGo(delta);
    };

    const patchedBack: History["back"] = function patched() {
      if (!confirmLeave()) {
        return;
      }
      rawBack();
    };

    const patchedForward: History["forward"] = function patched() {
      if (!confirmLeave()) {
        return;
      }
      rawForward();
    };

    window.history.pushState = patchedPushState;
    window.history.replaceState = patchedReplaceState;
    window.history.go = patchedGo;
    window.history.back = patchedBack;
    window.history.forward = patchedForward;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = leaveConfirmText;
    };
    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.history.pushState = rawPushState;
      window.history.replaceState = rawReplaceState;
      window.history.go = rawGo;
      window.history.back = rawBack;
      window.history.forward = rawForward;
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [leaveConfirmText, shouldBlockLeave]);

  const artifactRecords = useMemo<ProjectPipelineArtifactRecord[]>(() => {
    if (runDetail?.artifact_records?.length) {
      return runDetail.artifact_records.filter((item) => isPreviewablePath(item.path));
    }

    return projectFiles
      .filter((file) => isPreviewablePath(file.path))
      .filter((file) => !hideBuiltInFiles || !isBuiltInProjectFile(file.path))
      .map((file) => ({
        artifact_id: `source:${file.path}`,
        path: file.path,
        name: file.filename || file.path,
        kind: "source",
        format: file.path.split(".").pop() || "bin",
        human_readable: true,
        run_id: selectedRunId || "",
        producer_step_id: null,
        producer_step_name: null,
        consumer_step_ids: [],
        consumer_step_names: [],
        created_at: file.modified_time,
      }));
  }, [hideBuiltInFiles, projectFiles, runDetail?.artifact_records, selectedRunId]);

  const relatedArtifactPathsForSelectedStep = useMemo(() => {
    if (!selectedStepId) {
      return new Set<string>();
    }
    return new Set(
      artifactRecords
        .filter(
          (item) =>
            item.producer_step_id === selectedStepId ||
            item.consumer_step_ids.includes(selectedStepId),
        )
        .map((item) => item.path),
    );
  }, [artifactRecords, selectedStepId]);

  const visibleArtifactRecords = useMemo(() => {
    if (!selectedStepId) {
      return artifactRecords;
    }
    return artifactRecords.filter((item) => relatedArtifactPathsForSelectedStep.has(item.path));
  }, [artifactRecords, relatedArtifactPathsForSelectedStep, selectedStepId]);

  const groupedArtifactRecords = useMemo(
    () => [
      {
        key: "source",
        title: t("projects.artifacts.source", "Source Files"),
        items: visibleArtifactRecords.filter((item) => item.kind === "source"),
      },
      {
        key: "intermediate",
        title: t("projects.artifacts.intermediate", "Intermediate Artifacts"),
        items: visibleArtifactRecords.filter((item) => item.kind === "intermediate"),
      },
      {
        key: "final",
        title: t("projects.artifacts.final", "Final Outputs"),
        items: visibleArtifactRecords.filter((item) => item.kind === "final"),
      },
    ].filter((group) => group.items.length > 0),
    [t, visibleArtifactRecords],
  );

  const selectedArtifactRecord = useMemo(
    () => artifactRecords.find((item) => item.path === selectedFilePath),
    [artifactRecords, selectedFilePath],
  );

  const highlightedStepIds = useMemo(() => {
    const ids = new Set<string>();
    if (selectedStepId) {
      ids.add(selectedStepId);
    }
    if (selectedArtifactRecord?.producer_step_id) {
      ids.add(selectedArtifactRecord.producer_step_id);
    }
    for (const consumerStepId of selectedArtifactRecord?.consumer_step_ids || []) {
      ids.add(consumerStepId);
    }
    return ids;
  }, [selectedArtifactRecord, selectedStepId]);

  const selectedRunSummary = useMemo(
    () =>
      pipelineRuns.find(
        (run) => run.id === selectedRunId && run.template_id === selectedTemplateId,
      ),
    [pipelineRuns, selectedRunId, selectedTemplateId],
  );

  const runsForSelectedTemplate = useMemo(
    () =>
      pipelineRuns.filter(
        (run) => !selectedTemplateId || run.template_id === selectedTemplateId,
      ),
    [pipelineRuns, selectedTemplateId],
  );

  const activeRunTemplate = useMemo(() => {
    if (!selectedTemplateId) {
      return pipelineTemplates[0];
    }
    return (
      pipelineTemplates.find((item) => item.id === selectedTemplateId) ||
      pipelineTemplates[0]
    );
  }, [pipelineTemplates, selectedTemplateId]);

  const selectedTemplate = useMemo(
    () => pipelineTemplates.find((item) => item.id === selectedTemplateId),
    [pipelineTemplates, selectedTemplateId],
  );

  const currentStepIds = useMemo(
    () =>
      (runDetail?.steps?.map((step) => step.id) || activeRunTemplate?.steps?.map((step) => step.id) || []).filter(
        Boolean,
      ),
    [activeRunTemplate?.steps, runDetail?.steps],
  );

  const stepContractById = useMemo(() => {
    const mapping = new Map<string, ProjectPipelineTemplateInfo["steps"][number]>();
    for (const item of activeRunTemplate?.steps || []) {
      mapping.set(item.id, item);
    }
    return mapping;
  }, [activeRunTemplate?.steps]);

  const activeRunChatId = useMemo(
    () => runFocusChatId || runDetail?.focus_chat_id || selectedRunSummary?.focus_chat_id || "",
    [runDetail?.focus_chat_id, runFocusChatId, selectedRunSummary?.focus_chat_id],
  );

  const activeDesignChatId = useMemo(() => designFocusChatId, [designFocusChatId]);

  const runProgress = useMemo(() => {
    if (!runDetail) {
      return { total: 0, completed: 0, running: 0, pending: 0 };
    }
    const total = runDetail.steps.length;
    const completed = runDetail.steps.filter(
      (step) => step.status === "succeeded" || step.status === "completed",
    ).length;
    const running = runDetail.steps.filter((step) => step.status === "running").length;
    const pending = runDetail.steps.filter((step) => step.status === "pending").length;
    return { total, completed, running, pending };
  }, [runDetail]);

  const latestRunForSelectedTemplate = useMemo(() => {
    if (runsForSelectedTemplate.length === 0) {
      return null;
    }
    const sorted = [...runsForSelectedTemplate].sort((a, b) =>
      toTimestamp(b.updated_at || b.created_at) -
      toTimestamp(a.updated_at || a.created_at),
    );
    return sorted[0] || null;
  }, [runsForSelectedTemplate]);

  const succeededRunCountForSelectedTemplate = useMemo(
    () => runsForSelectedTemplate.filter((item) => isSucceededStatus(item.status)).length,
    [runsForSelectedTemplate],
  );

  const selectedRunAllStepsSucceeded = useMemo(() => {
    if (!runDetail || runDetail.steps.length === 0) {
      return false;
    }
    return runDetail.steps.every((step) => isSucceededStatus(step.status));
  }, [runDetail]);

  const selectedRunEvidenceCoverage = useMemo(() => {
    if (!runDetail || runDetail.steps.length === 0) {
      return false;
    }
    return runDetail.steps.every((step) => (step.evidence || []).length > 0);
  }, [runDetail]);

  const hasTwoSucceededRuns = succeededRunCountForSelectedTemplate >= 2;
  const canPromoteToTemplateDraft =
    hasTwoSucceededRuns && selectedRunAllStepsSucceeded && selectedRunEvidenceCoverage;

  const verificationGateSummary = useMemo(
    () =>
      [
        `连续成功>=2: ${hasTwoSucceededRuns ? "yes" : "no"}`,
        `当前运行步骤全成功: ${selectedRunAllStepsSucceeded ? "yes" : "no"}`,
        `当前运行证据覆盖: ${selectedRunEvidenceCoverage ? "yes" : "no"}`,
      ].join("; "),
    [hasTwoSucceededRuns, selectedRunAllStepsSucceeded, selectedRunEvidenceCoverage],
  );

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await agentsApi.listAgents();
      setAgents(data.agents);
    } catch (err) {
      console.error("failed to load agent projects", err);
      setError(
        t(
          "projects.loadFailed",
          "Failed to load projects for the current agent.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [setAgents, t]);

  const loadProjectFiles = useCallback(async (
    agentId: string,
    project: AgentProjectSummary,
  ) => {
    setFilesLoading(true);
    setSelectedFilePath("");
    setFileContent("");
    const projectIds = buildProjectIdCandidates(project);
    let loaded = false;
    try {
      for (const projectRequestId of projectIds) {
        try {
          const files = await agentsApi.listProjectFiles(agentId, projectRequestId);
          setProjectFiles(files);
          setResolvedProjectRequestId(projectRequestId);
          const defaultFile = files.find((item) => isPreviewablePath(item.path));
          if (defaultFile) {
            setSelectedFilePath(defaultFile.path);
          }
          loaded = true;
          break;
        } catch {
          // Try next id candidate.
        }
      }

      if (!loaded) {
        throw new Error("project_files_not_found");
      }
    } catch (err) {
      console.error("failed to load project files", err);
      setProjectFiles([]);
      setError(
        t("projects.loadFilesFailed", "Failed to load files for this project."),
      );
    } finally {
      setFilesLoading(false);
    }
  }, [t]);

  const loadFileContent = useCallback(async (
    agentId: string,
    project: AgentProjectSummary,
    filePath: string,
  ) => {
    setContentLoading(true);
    setFileContent("");
    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(project)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));
    try {
      let loaded = false;
      for (const projectRequestId of uniqueProjectIds) {
        try {
          const data = await agentsApi.readProjectFile(
            agentId,
            projectRequestId,
            filePath,
          );
          setFileContent(data.content);
          setResolvedProjectRequestId(projectRequestId);
          loaded = true;
          break;
        } catch {
          // Try next id candidate.
        }
      }
      if (!loaded) {
        throw new Error("project_file_content_not_found");
      }
    } catch (err) {
      console.error("failed to load project file content", err);
      setFileContent(
        t(
          "projects.previewLoadFailed",
          "Unable to preview this file. It might be binary or inaccessible.",
        ),
      );
    } finally {
      setContentLoading(false);
    }
  }, [resolvedProjectRequestId, t]);

  const fetchProjectFileContent = useCallback(async (
    agentId: string,
    project: AgentProjectSummary,
    filePath: string,
  ): Promise<string> => {
    if (selectedFilePath === filePath && fileContent) {
      return fileContent;
    }

    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(project)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));

    for (const projectRequestId of uniqueProjectIds) {
      try {
        const data = await agentsApi.readProjectFile(
          agentId,
          projectRequestId,
          filePath,
        );
        setResolvedProjectRequestId(projectRequestId);
        return data.content;
      } catch {
        // Try next id candidate.
      }
    }

    throw new Error("project_file_content_not_found");
  }, [fileContent, resolvedProjectRequestId, selectedFilePath]);

  const loadRunDetail = useCallback(async (
    agentId: string,
    project: AgentProjectSummary,
    runId: string,
  ) => {
    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(project)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));
    try {
      let loaded = false;
      for (const projectRequestId of uniqueProjectIds) {
        try {
          const detail = await agentsApi.getProjectPipelineRun(
            agentId,
            projectRequestId,
            runId,
          );
          setRunDetail(detail);
          setResolvedProjectRequestId(projectRequestId);
          if (detail.artifacts.length > 0 && !selectedFilePath) {
            setSelectedFilePath(detail.artifacts[0]);
          }
          loaded = true;
          break;
        } catch {
          // Try next id candidate.
        }
      }
      if (!loaded) {
        throw new Error("project_run_not_found");
      }
    } catch (err) {
      console.error("failed to load pipeline run detail", err);
      setRunDetail(null);
      setError(
        t("projects.pipeline.loadRunFailed", "Failed to load pipeline run detail."),
      );
    }
  }, [resolvedProjectRequestId, selectedFilePath, t]);

  const loadPipelineContext = useCallback(async (
    agentId: string,
    project: AgentProjectSummary,
  ) => {
    setPipelineLoading(true);
    const projectIds = buildProjectIdCandidates(project);
    try {
      let templates: ProjectPipelineTemplateInfo[] = [];
      let runs: ProjectPipelineRunSummary[] = [];
      let loaded = false;

      for (const projectRequestId of projectIds) {
        try {
          const [templateData, runData] = await Promise.all([
            agentsApi.listProjectPipelineTemplates(agentId, projectRequestId),
            agentsApi.listProjectPipelineRuns(agentId, projectRequestId),
          ]);
          templates = templateData;
          runs = runData;
          setResolvedProjectRequestId(projectRequestId);
          loaded = true;
          break;
        } catch {
          // Try next id candidate.
        }
      }

      if (!loaded) {
        throw new Error("project_pipeline_context_not_found");
      }

      setError("");
      setPipelineTemplates(templates);
      setPipelineRuns(runs);

      if (templates.length > 0) {
        setSelectedTemplateId((prev) =>
          templates.some((item) => item.id === prev) ? prev : templates[0].id,
        );
      } else {
        setSelectedTemplateId("");
      }

      if (runs.length > 0) {
        setSelectedRunId((prev) => (runs.some((item) => item.id === prev) ? prev : ""));
      } else {
        setSelectedRunId("");
        setRunDetail(null);
      }
    } catch (err) {
      console.error("failed to load pipeline context", err);
      setPipelineTemplates([]);
      setPipelineRuns([]);
      setSelectedTemplateId("");
      setSelectedRunId("");
      setRunDetail(null);
      setError(
        `${t("projects.pipeline.loadFailed", "Failed to load pipeline templates and runs.")} ${(err as Error)?.message || ""}`.trim(),
      );
    } finally {
      setPipelineLoading(false);
    }
  }, [t]);

  const handleOpenImportModal = useCallback(async () => {
    if (!currentAgent) {
      return;
    }
    setImportLoading(true);
    try {
      const templates = await agentsApi.listPlatformFlowTemplates(currentAgent.id);
      setPlatformTemplates(templates);
      setSelectedPlatformTemplateId((prev) => {
        if (prev && templates.some((item) => item.id === prev)) {
          return prev;
        }
        return templates[0]?.id || "";
      });
      setImportModalOpen(true);
    } catch (err) {
      console.error("failed to load platform templates", err);
      message.error(
        t("projects.pipeline.loadGlobalFailed", "Failed to load global pipeline templates."),
      );
    } finally {
      setImportLoading(false);
    }
  }, [currentAgent, t]);

  const handleImportPlatformTemplate = useCallback(async () => {
    if (!currentAgent || !selectedProject || !selectedPlatformTemplateId) {
      return;
    }

    setImportLoading(true);
    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(selectedProject)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));

    try {
      let importedTemplateId = "";
      let imported = false;

      for (const projectRequestId of uniqueProjectIds) {
        try {
          const result = await agentsApi.importPlatformTemplateIntoProject(
            currentAgent.id,
            projectRequestId,
            { platform_template_id: selectedPlatformTemplateId },
          );
          setResolvedProjectRequestId(projectRequestId);
          importedTemplateId = result.id;
          imported = true;
          break;
        } catch {
          // Try next candidate id.
        }
      }

      if (!imported) {
        throw new Error("import_platform_template_failed");
      }

      await loadPipelineContext(currentAgent.id, selectedProject);
      if (importedTemplateId) {
        setSelectedTemplateId(importedTemplateId);
      }
      setImportModalOpen(false);
      message.success(
        t("projects.pipeline.importGlobalSuccess", "Global template imported to current project."),
      );
    } catch (err) {
      console.error("failed to import global template", err);
      message.error(
        t("projects.pipeline.importGlobalFailed", "Failed to import global template."),
      );
    } finally {
      setImportLoading(false);
    }
  }, [
    currentAgent,
    loadPipelineContext,
    resolvedProjectRequestId,
    selectedPlatformTemplateId,
    selectedProject,
    t,
  ]);

  const pollPipelineRun = useCallback(async (
    agentId: string,
    project: AgentProjectSummary,
    runId: string,
  ) => {
    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(project)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));
    try {
      for (const projectRequestId of uniqueProjectIds) {
        try {
          const [runs, detail] = await Promise.all([
            agentsApi.listProjectPipelineRuns(agentId, projectRequestId),
            agentsApi.getProjectPipelineRun(agentId, projectRequestId, runId),
          ]);
          setPipelineRuns(runs);
          setRunDetail(detail);
          setResolvedProjectRequestId(projectRequestId);
          return;
        } catch {
          // Try next id candidate.
        }
      }
    } catch (err) {
      console.error("failed to poll pipeline run", err);
    }
  }, [resolvedProjectRequestId]);

  const handleCreateRun = useCallback(async () => {
    if (!currentAgent || !selectedProject || !selectedTemplateId) {
      return;
    }
    setCreateRunLoading(true);
    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(selectedProject)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));
    try {
      let run: ProjectPipelineRunDetail | null = null;
      let requestProjectId = "";
      for (const projectRequestId of uniqueProjectIds) {
        try {
          run = await agentsApi.createProjectPipelineRun(
            currentAgent.id,
            projectRequestId,
            { template_id: selectedTemplateId },
          );
          requestProjectId = projectRequestId;
          setResolvedProjectRequestId(projectRequestId);
          break;
        } catch {
          // Try next id candidate.
        }
      }

      if (!run) {
        throw new Error("project_pipeline_run_create_failed");
      }

      await loadPipelineContext(currentAgent.id, selectedProject);
      setSelectedRunId(run.id);
      setRunDetail(run);

      const prevFocusChatId = runFocusChatIdRef.current;
      if (prevFocusChatId) {
        void chatApi
          .clearChatMeta(prevFocusChatId, {
            user_id: "default",
            channel: "console",
          })
          .catch(() => {});
      }
      void chatApi.createChat({
        name: `[focus] ${selectedProject.name}`,
        session_id: `project-run-${run.id}`,
        user_id: "default",
        channel: "console",
        meta: {
          focus_type: "project_run",
          focus_id: selectedProject.id,
          project_id: selectedProject.id,
          project_request_id: requestProjectId || selectedProject.id,
          run_id: run.id,
          focus_path: `projects/${selectedProject.id}`,
        },
      }).then((chat) => {
        setRunFocusChatId(chat.id);
      }).catch((err) => {
        console.warn("[focus] failed to create project focus chat", err);
      });
    } catch (err) {
      console.error("failed to create pipeline run", err);
      setError(
        t("projects.pipeline.createRunFailed", "Failed to start pipeline run."),
      );
    } finally {
      setCreateRunLoading(false);
    }
  }, [currentAgent, loadPipelineContext, resolvedProjectRequestId, selectedProject, selectedTemplateId, t]);

  const handleEnsureRunChat = useCallback(async (forceNew = false): Promise<string> => {
    if (!selectedProject || !selectedRunId) {
      return "";
    }

    if (!forceNew && activeRunChatId) {
      return activeRunChatId;
    }

    setChatStarting(true);
    try {
      const previousChatId = runFocusChatIdRef.current;
      if (forceNew && previousChatId) {
        void chatApi
          .clearChatMeta(previousChatId, {
            user_id: "default",
            channel: "console",
          })
          .catch(() => {});
      }

      const created = await chatApi.createChat({
        name: `[focus] ${selectedProject.name}`,
        session_id: `project-run-${selectedRunId}-${Date.now()}`,
        user_id: "default",
        channel: "console",
        meta: {
          focus_type: "project_run",
          focus_id: selectedProject.id,
          project_id: selectedProject.id,
          project_request_id: resolvedProjectRequestId || selectedProject.id,
          run_id: selectedRunId,
          focus_path: `projects/${selectedProject.id}`,
        },
      });

      setRunFocusChatId(created.id);
      setError("");
      return created.id;
    } catch (err) {
      console.error("failed to create project run chat", err);
      setError(t("projects.chat.startFailed", "Failed to start project chat."));
      return "";
    } finally {
      setChatStarting(false);
    }
  }, [activeRunChatId, resolvedProjectRequestId, selectedProject, selectedRunId, t]);

  const resolveLatestDesignBoundChatId = useCallback(async (): Promise<string> => {
    if (!selectedProject || !currentAgent) {
      return "";
    }

    const templateId = selectedTemplateId || "draft";
    const bindingKey = buildProjectFlowBindingKey({
      projectId: selectedProject.id,
      templateId,
    });

    const chats = await chatApi.listChats({ user_id: "default", channel: "console" });
    const matched = chats.filter((chat) => {
      const meta =
        chat.meta && typeof chat.meta === "object"
          ? (chat.meta as Record<string, unknown>)
          : undefined;
      const metaType = getMetaString(meta, "focus_type") || getMetaString(meta, "binding_type");
      const metaKey = getMetaString(meta, "focus_binding_key") || getMetaString(meta, "pipeline_binding_key");
      const metaAgentId = getMetaString(meta, "agent_id");
      if (metaType !== "pipeline_edit" || metaKey !== bindingKey) {
        return false;
      }
      if (metaAgentId && metaAgentId !== currentAgent.id) {
        return false;
      }
      return true;
    });

    if (matched.length === 0) {
      const sessionPrefix = `project-flow-design-${selectedProject.id}-`;
      const bySession = chats.filter((chat) =>
        (chat.session_id || "").startsWith(sessionPrefix),
      );
      if (bySession.length > 0) {
        const sorted = sortChatsForRestore(bySession);
        return sorted[0]?.id || "";
      }
    }

    if (matched.length === 0) {
      return "";
    }

    const sorted = sortChatsForRestore(matched);
    return sorted[0]?.id || "";
  }, [currentAgent, selectedProject, selectedTemplateId]);

  const resolveLatestRunBoundChatId = useCallback(async (): Promise<string> => {
    if (!selectedProject || !selectedRunId) {
      return "";
    }

    const chats = await chatApi.listChats({ user_id: "default", channel: "console" });
    const matched = chats.filter((chat) => {
      const meta =
        chat.meta && typeof chat.meta === "object"
          ? (chat.meta as Record<string, unknown>)
          : undefined;
      const metaType = getMetaString(meta, "focus_type");
      const metaRunId = getMetaString(meta, "run_id");
      const metaProjectId = getMetaString(meta, "project_id");
      if (metaType !== "project_run" || metaRunId !== selectedRunId) {
        return false;
      }
      if (metaProjectId && metaProjectId !== selectedProject.id) {
        return false;
      }
      return true;
    });

    if (matched.length === 0) {
      const sessionPrefix = `project-run-${selectedRunId}-`;
      const bySession = chats.filter((chat) =>
        (chat.session_id || "").startsWith(sessionPrefix),
      );
      if (bySession.length > 0) {
        const sorted = sortChatsForRestore(bySession);
        return sorted[0]?.id || "";
      }
    }

    if (matched.length === 0) {
      return "";
    }

    const sorted = sortChatsForRestore(matched);
    return sorted[0]?.id || "";
  }, [selectedProject, selectedRunId]);

  const handleEnsureDesignChat = useCallback(async (forceNew = false, allowCreate = true): Promise<string> => {
    if (!selectedProject || !currentAgent) {
      return "";
    }

    if (!forceNew && activeDesignChatId) {
      return activeDesignChatId;
    }

    setChatStarting(true);
    try {
      const previousChatId = designFocusChatIdRef.current;
      if (forceNew && previousChatId) {
        void chatApi
          .clearChatMeta(previousChatId, {
            user_id: "default",
            channel: "console",
          })
          .catch(() => {});
      }

      const templateId = selectedTemplateId || "draft";
      const bindingKey = buildProjectFlowBindingKey({
        projectId: selectedProject.id,
        templateId,
      });
      const focusPath = buildProjectFlowWorkspaceRelativePath(selectedProject.id);
      const flowMemoryPath = buildProjectFlowMemoryRelativePath(selectedProject.id);
      const selectedTemplateName = selectedTemplate?.name || selectedProject.name;

      if (!forceNew) {
        const restoredChatId = await resolveLatestDesignBoundChatId();
        if (restoredChatId) {
          setDesignFocusChatId(restoredChatId);
          setError("");
          return restoredChatId;
        }

        if (!allowCreate) {
          return "";
        }
      }

      const created = await chatApi.createChat({
        name: `[flow] ${selectedProject.name}`,
        session_id: `project-flow-design-${selectedProject.id}-${Date.now()}`,
        user_id: "default",
        channel: "console",
        meta: {
          focus_type: "pipeline_edit",
          focus_binding_key: bindingKey,
          focus_id: templateId,
          focus_path: focusPath,
          focus_scope: "project",
          focus_flow_memory_path: flowMemoryPath,
          // Legacy compatibility fields
          binding_type: "pipeline_edit",
          pipeline_binding_key: bindingKey,
          pipeline_id: templateId,
          pipeline_name: selectedTemplate?.name || selectedProject.name,
          pipeline_version: (selectedTemplate?.version || "0").trim() || "0",
          pipeline_scope: "project",
          agent_id: currentAgent.id,
          flow_memory_path: flowMemoryPath,
          project_id: selectedProject.id,
          project_request_id: resolvedProjectRequestId || selectedProject.id,
        },
      });

      setDesignFocusChatId(created.id);
      const sourceFiles = projectFiles
        .map((item) => item.path)
        .filter((item) => isPreviewablePath(item))
        .slice(0, 200);
      const bootstrapPrompt = buildProjectFlowBootstrapPrompt({
        projectName: selectedProject.name,
        selectedTemplateName,
        flowMemoryPath,
        workspaceDir: selectedProject.workspace_dir || "",
        sourceFiles,
      });
      void chatApi.startConsoleChat({
        sessionId: created.session_id,
        prompt: bootstrapPrompt,
        userId: "default",
        channel: "console",
      }).catch((err) => {
        console.warn("failed to start design bootstrap prompt", err);
      });
      setError("");
      return created.id;
    } catch (err) {
      console.error("failed to create project flow design chat", err);
      setError(t("projects.chat.startFailed", "Failed to start project chat."));
      return "";
    } finally {
      setChatStarting(false);
    }
  }, [
    activeDesignChatId,
    currentAgent,
    resolvedProjectRequestId,
    projectFiles,
    selectedProject,
    selectedTemplate?.name,
    selectedTemplate?.version,
    selectedTemplateId,
    resolveLatestDesignBoundChatId,
    t,
  ]);

  useEffect(() => {
    runFocusChatIdRef.current = runFocusChatId;
  }, [runFocusChatId]);

  useEffect(() => {
    designFocusChatIdRef.current = designFocusChatId;
  }, [designFocusChatId]);

  useEffect(() => {
    const fallbackChatId = runDetail?.focus_chat_id || selectedRunSummary?.focus_chat_id || "";
    if (fallbackChatId && fallbackChatId !== runFocusChatId) {
      setRunFocusChatId(fallbackChatId);
    }
  }, [runDetail?.focus_chat_id, runFocusChatId, selectedRunSummary?.focus_chat_id]);

  useEffect(() => {
    if (!currentAgent) {
      void loadAgents();
    }
  }, [currentAgent, loadAgents]);

  useEffect(() => {
    setResolvedProjectRequestId("");
    setProjectFiles([]);
    setSelectedFilePath("");
    setFileContent("");
    setPipelineTemplates([]);
    setPipelineRuns([]);
    setSelectedTemplateId("");
    setSelectedRunId("");
    setSelectedStepId("");
    setRunDetail(null);
    setRunFocusChatId("");
    setDesignFocusChatId("");
    setUploadModalOpen(false);
    setPendingUploads([]);
    setUploadTargetDir("data");
    setSelectedAttachPaths([]);
    setSendingSelectedFiles(false);
    designRestoreAttemptKeyRef.current = "";
    runRestoreAttemptKeyRef.current = "";
  }, [routeProjectId]);

  useEffect(() => {
    const query = new URLSearchParams(location.search);
    if (query.get("openUpload") !== "1") {
      return;
    }
    setUploadModalOpen(true);
    query.delete("openUpload");
    const next = query.toString();
    navigate(`${location.pathname}${next ? `?${next}` : ""}`, { replace: true });
  }, [location.pathname, location.search, navigate]);

  useEffect(() => {
    if (!selectedStepId) {
      return;
    }
    if (!currentStepIds.includes(selectedStepId)) {
      setSelectedStepId("");
    }
  }, [currentStepIds, selectedStepId]);

  useEffect(() => {
    if (!selectedStepId) {
      return;
    }
    if (selectedFilePath && relatedArtifactPathsForSelectedStep.has(selectedFilePath)) {
      return;
    }
    const firstRelatedPath = Array.from(relatedArtifactPathsForSelectedStep)[0];
    if (firstRelatedPath) {
      setSelectedFilePath(firstRelatedPath);
    }
  }, [relatedArtifactPathsForSelectedStep, selectedFilePath, selectedStepId]);

  useEffect(() => {
    if (!selectedFilePath) {
      return;
    }
    const stillVisible = artifactRecords.some((item) => item.path === selectedFilePath);
    if (!stillVisible) {
      setSelectedFilePath("");
    }
  }, [artifactRecords, selectedFilePath]);

  useEffect(() => {
    if (!currentAgent || !selectedProject) {
      return;
    }
    void loadProjectFiles(currentAgent.id, selectedProject);
    void loadPipelineContext(currentAgent.id, selectedProject);
  }, [currentAgent, selectedProject, loadProjectFiles, loadPipelineContext]);

  useEffect(() => {
    if (!currentAgent || !selectedProject) {
      return;
    }
    if (selectedRunId || activeDesignChatId || pipelineLoading || chatStarting) {
      return;
    }

    const templateId = selectedTemplateId || "draft";
    const restoreKey = `${currentAgent.id}:${selectedProject.id}:${templateId}`;
    if (designRestoreAttemptKeyRef.current === restoreKey) {
      return;
    }
    designRestoreAttemptKeyRef.current = restoreKey;

    void handleEnsureDesignChat(false, true);
  }, [
    activeDesignChatId,
    chatStarting,
    currentAgent,
    handleEnsureDesignChat,
    pipelineLoading,
    selectedProject,
    selectedRunId,
    selectedTemplateId,
  ]);

  useEffect(() => {
    if (!currentAgent || !selectedProject || !selectedRunId) {
      return;
    }
    if (activeRunChatId || pipelineLoading || chatStarting) {
      return;
    }

    const restoreKey = `${currentAgent.id}:${selectedProject.id}:${selectedRunId}`;
    if (runRestoreAttemptKeyRef.current === restoreKey) {
      return;
    }
    runRestoreAttemptKeyRef.current = restoreKey;

    let cancelled = false;
    void resolveLatestRunBoundChatId()
      .then((restoredChatId) => {
        if (cancelled || !restoredChatId) {
          return;
        }
        setRunFocusChatId((prev) => prev || restoredChatId);
        setError("");
      })
      .catch(() => {
        // Keep silent for passive restore checks.
      });

    return () => {
      cancelled = true;
    };
  }, [
    activeRunChatId,
    chatStarting,
    currentAgent,
    pipelineLoading,
    resolveLatestRunBoundChatId,
    selectedProject,
    selectedRunId,
  ]);

  useEffect(() => {
    if (!currentAgent || !selectedProject || !selectedFilePath) {
      return;
    }
    void loadFileContent(currentAgent.id, selectedProject, selectedFilePath);
  }, [currentAgent, selectedProject, selectedFilePath, loadFileContent]);

  useEffect(() => {
    if (!selectedTemplateId) {
      setSelectedRunId("");
      setRunDetail(null);
      return;
    }

    if (runsForSelectedTemplate.length === 0) {
      setSelectedRunId("");
      setRunDetail(null);
      return;
    }

    setSelectedRunId((prev) =>
      runsForSelectedTemplate.some((item) => item.id === prev)
        ? prev
        : runsForSelectedTemplate[0].id,
    );
  }, [runsForSelectedTemplate, selectedTemplateId]);

  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null);
    }
  }, [selectedRunId]);

  useEffect(() => {
    if (!currentAgent || !selectedProject || !selectedRunId) {
      return;
    }
    void loadRunDetail(currentAgent.id, selectedProject, selectedRunId);
  }, [currentAgent, selectedProject, selectedRunId, loadRunDetail]);

  useEffect(() => {
    if (!currentAgent || !selectedProject || !selectedRunId) {
      return;
    }

    const runStatus = runDetail?.status || selectedRunSummary?.status;
    if (runStatus !== "running" && runStatus !== "pending") {
      return;
    }

    const timer = window.setInterval(() => {
      void pollPipelineRun(currentAgent.id, selectedProject, selectedRunId);
    }, 5000);

    return () => {
      window.clearInterval(timer);
    };
  }, [
    currentAgent,
    selectedProject,
    selectedRunId,
    runDetail?.status,
    selectedRunSummary?.status,
    pollPipelineRun,
  ]);

  const handleSelectStep = useCallback((stepId: string) => {
    setSelectedStepId((prev) => (prev === stepId ? "" : stepId));
  }, []);

  const handleUploadFiles = useCallback(async () => {
    if (!currentAgent || !selectedProject || pendingUploads.length === 0) {
      return;
    }

    setUploadingFiles(true);
    const projectIds = [resolvedProjectRequestId, ...buildProjectIdCandidates(selectedProject)]
      .map((item) => item.trim())
      .filter(Boolean);
    const uniqueProjectIds = Array.from(new Set(projectIds));
    try {
      let uploadedCount = 0;
      for (const file of pendingUploads) {
        let uploaded = false;
        for (const projectRequestId of uniqueProjectIds) {
          try {
            await agentsApi.uploadProjectFile(
              currentAgent.id,
              projectRequestId,
              file,
              uploadTargetDir || "data",
            );
            setResolvedProjectRequestId(projectRequestId);
            uploaded = true;
            uploadedCount += 1;
            break;
          } catch {
            // Try next id candidate.
          }
        }
        if (!uploaded) {
          throw new Error(`upload_failed:${file.name}`);
        }
      }

      await loadProjectFiles(currentAgent.id, selectedProject);
      setUploadModalOpen(false);
      setPendingUploads([]);
      message.success(
        t("projects.upload.success", "Uploaded {{count}} file(s) to project.", {
          count: uploadedCount,
        }),
      );
    } catch (err) {
      console.error("failed to upload project files", err);
      message.error(t("projects.upload.failed", "Failed to upload project files."));
    } finally {
      setUploadingFiles(false);
    }
  }, [
    currentAgent,
    loadProjectFiles,
    pendingUploads,
    resolvedProjectRequestId,
    selectedProject,
    t,
    uploadTargetDir,
  ]);

  const handleDeleteProject = useCallback(async () => {
    if (!currentAgent || !selectedProject) {
      return;
    }

    setDeletingProject(true);
    try {
      await agentsApi.deleteProject(currentAgent.id, selectedProject.id);
      message.success(
        t("projects.deleteSuccess", "Project deleted: {{name}}", {
          name: selectedProject.name || selectedProject.id,
        }),
      );
      await loadAgents();
      navigate("/projects");
    } catch (err) {
      console.error("failed to delete project", err);
      message.error(t("projects.deleteFailed", "Failed to delete project."));
    } finally {
      setDeletingProject(false);
    }
  }, [currentAgent, loadAgents, navigate, selectedProject, t]);

  const handleSelectArtifactFile = useCallback((path: string) => {
    setSelectedFilePath(path);
  }, []);

  const buildAttachContentBySize = useCallback((params: {
    path: string;
    fileName: string;
    size: number;
    content: string;
  }): string => {
    const { path, fileName, size, content } = params;
    if (size <= INLINE_FULL_MAX_BYTES) {
      return content;
    }

    if (size <= INLINE_TRUNCATE_MAX_BYTES) {
      const head = content.slice(0, INLINE_TRUNCATE_HEAD_CHARS);
      const tail = content.slice(-INLINE_TRUNCATE_TAIL_CHARS);
      return [
        `[Truncated file for context window control]`,
        `file: ${fileName}`,
        `path: ${path}`,
        `size: ${size} bytes`,
        `--- HEAD ---`,
        head,
        `--- TAIL ---`,
        tail,
      ].join("\n");
    }

    return [
      `[Large file metadata only to avoid context overflow]`,
      `file: ${fileName}`,
      `path: ${path}`,
      `size: ${size} bytes`,
      `note: use this file name/path as reference and request focused extraction if needed.`,
    ].join("\n");
  }, []);

  const handleAttachArtifactToChat = useCallback((path: string) => {
    setSelectedAttachPaths((prev) =>
      prev.includes(path) ? prev.filter((item) => item !== path) : [...prev, path],
    );
  }, [
    setSelectedAttachPaths,
  ]);

  const handleSendSelectedFilesToChat = useCallback(async () => {
    if (!currentAgent || !selectedProject || selectedAttachPaths.length === 0) {
      return;
    }

    setSendingSelectedFiles(true);
    try {
      if (selectedRunId) {
        await handleEnsureRunChat();
      } else {
        await handleEnsureDesignChat();
      }

      if (!autoAnalyzeOnAttach) {
        const selectedFiles = selectedAttachPaths.map((path) => {
          const fileInfo = projectFiles.find((file) => file.path === path);
          return {
            path,
            size: fileInfo?.size || 0,
          };
        });
        setAutoAttachRequest({
          id: `manual-batch-draft-${Date.now()}`,
          mode: "draft",
          note: buildAttachDraftPrompt({
            projectName: selectedProject.name,
            selectedRunId,
            selectedFiles,
          }),
        });
        message.success(
          t(
            "projects.chat.attachDraftReady",
            "Prepared selected file context in the chat input box.",
          ),
        );
        setSelectedAttachPaths([]);
        return;
      }

      const filesPayload: Array<{ fileName: string; content: string; mimeType?: string }> = [];
      let remainingChars = INLINE_TOTAL_CHAR_BUDGET;

      for (const path of selectedAttachPaths) {
        const fileInfo = projectFiles.find((file) => file.path === path);
        const fileName = path.split("/").pop() || "project-file.txt";
        const size = fileInfo?.size || 0;

        if (remainingChars <= 0) {
          filesPayload.push({
            fileName,
            content: buildAttachContentBySize({ path, fileName, size, content: "" }),
            mimeType: "text/plain",
          });
          continue;
        }

        if (size > INLINE_TRUNCATE_MAX_BYTES) {
          filesPayload.push({
            fileName,
            content: buildAttachContentBySize({ path, fileName, size, content: "" }),
            mimeType: "text/plain",
          });
          remainingChars = Math.max(0, remainingChars - 300);
          continue;
        }

        const rawContent = await fetchProjectFileContent(currentAgent.id, selectedProject, path);
        const prepared = buildAttachContentBySize({ path, fileName, size, content: rawContent });
        const finalContent =
          prepared.length <= remainingChars
            ? prepared
            : `${prepared.slice(0, Math.max(800, remainingChars))}\n\n[Trimmed by total context budget]`;
        filesPayload.push({
          fileName,
          content: finalContent,
          mimeType: inferMimeTypeByPath(path),
        });
        remainingChars = Math.max(0, remainingChars - finalContent.length);
      }

      setAutoAttachRequest({
        id: `manual-batch-${Date.now()}`,
        mode: "submit",
        files: filesPayload,
        note: buildAutoAttachAnalysisPrompt({
          projectName: selectedProject.name,
          fileNames: filesPayload.map((item) => item.fileName),
          selectedRunId,
        }),
      });

      message.success(
        t("projects.chat.autoAttachBatchSent", "Queued {{count}} selected file(s) for chat.", {
          count: filesPayload.length,
        }),
      );
      setSelectedAttachPaths([]);
    } catch (err) {
      console.error("failed to send selected files to chat", err);
      message.error(
        t("projects.chat.autoAttachFailed", "Failed to attach selected file to chat."),
      );
    } finally {
      setSendingSelectedFiles(false);
    }
  }, [
    buildAttachContentBySize,
    currentAgent,
    fetchProjectFileContent,
    handleEnsureDesignChat,
    handleEnsureRunChat,
    projectFiles,
    selectedAttachPaths,
    selectedProject,
    selectedRunId,
    t,
    autoAnalyzeOnAttach,
  ]);

  const handlePrepareImplementationDraft = useCallback(async () => {
    if (!selectedProject) {
      return;
    }

    const chatId = await handleEnsureDesignChat(false, true);
    if (!chatId) {
      message.error(t("projects.chat.startFailed", "Failed to start project chat."));
      return;
    }

    setAutoAttachRequest({
      id: `flow-impl-${Date.now()}`,
      mode: "draft",
      note: buildImplementationAdvancePrompt({
        projectName: selectedProject.name,
        templateName: selectedTemplate?.name || "draft",
        templateId: selectedTemplateId || "draft",
        runCount: runsForSelectedTemplate.length,
        latestRunStatus: latestRunForSelectedTemplate?.status || "",
        gateSummary: verificationGateSummary,
      }),
    });
    message.success(
      t(
        "projects.chat.implDraftReady",
        "Implementation prompt has been prepared in the design chat input.",
      ),
    );
  }, [
    handleEnsureDesignChat,
    latestRunForSelectedTemplate?.status,
    runsForSelectedTemplate.length,
    selectedProject,
    selectedTemplate?.name,
    selectedTemplateId,
    t,
    verificationGateSummary,
  ]);

  const handlePrepareValidationDraft = useCallback(async () => {
    if (!selectedProject) {
      return;
    }
    if (!selectedRunId) {
      message.warning(
        t(
          "projects.pipeline.validationNeedRun",
          "Please start or select one run before preparing a validation prompt.",
        ),
      );
      return;
    }

    const chatId = await handleEnsureRunChat(false);
    if (!chatId) {
      message.error(t("projects.chat.startFailed", "Failed to start project chat."));
      return;
    }

    setAutoAttachRequest({
      id: `flow-validate-${Date.now()}`,
      mode: "draft",
      note: buildValidationRoundPrompt({
        projectName: selectedProject.name,
        runId: selectedRunId,
        templateName: selectedTemplate?.name || selectedTemplateId || "draft",
        gateSummary: verificationGateSummary,
      }),
    });
    message.success(
      t(
        "projects.chat.validationDraftReady",
        "Validation prompt has been prepared in the run chat input.",
      ),
    );
  }, [
    handleEnsureRunChat,
    selectedProject,
    selectedRunId,
    selectedTemplate?.name,
    selectedTemplateId,
    t,
    verificationGateSummary,
  ]);

  const handlePreparePromotionDraft = useCallback(async () => {
    if (!selectedProject || !selectedTemplateId || !selectedRunId) {
      return;
    }

    const chatId = await handleEnsureDesignChat(false, true);
    if (!chatId) {
      message.error(t("projects.chat.startFailed", "Failed to start project chat."));
      return;
    }

    setAutoAttachRequest({
      id: `flow-promote-${Date.now()}`,
      mode: "draft",
      note: buildPromotionDraftPrompt({
        projectName: selectedProject.name,
        templateName: selectedTemplate?.name || selectedTemplateId,
        templateId: selectedTemplateId,
        runId: selectedRunId,
      }),
    });
    message.success(
      t(
        "projects.chat.promotionDraftReady",
        "Promotion draft prompt has been prepared in the design chat input.",
      ),
    );
  }, [
    handleEnsureDesignChat,
    selectedProject,
    selectedRunId,
    selectedTemplate?.name,
    selectedTemplateId,
    t,
  ]);

  return (
    <div className={styles.agentsPage}>
      <div className={styles.header}>
        <div>
          <Title level={4} className={styles.title}>
            {t("projects.detailTitle", "Project Detail")}
          </Title>
          <Text type="secondary" className={styles.description}>
            {t(
              "projects.detailDescription",
              "Inspect artifacts, pipeline runs, and execution evidence for this project.",
            )}
          </Text>
        </div>
        <div className={styles.headerActions}>
          {selectedProject ? (
            <>
              <Button size="small" onClick={() => setUploadModalOpen(true)}>
                {t("projects.upload.button", "Upload Files")}
              </Button>
              <Popconfirm
                title={t(
                  "projects.deleteConfirmTitleWithName",
                  "Delete project {{name}}?",
                  { name: selectedProject.name || selectedProject.id },
                )}
                description={t(
                  "projects.deleteConfirmDescription",
                  "This action is irreversible and will permanently delete {{name}} and all project files.",
                  { name: selectedProject.name || selectedProject.id },
                )}
                okText={t("common.delete", "Delete")}
                cancelText={t("common.cancel", "Cancel")}
                okButtonProps={{ danger: true, loading: deletingProject }}
                onConfirm={() => void handleDeleteProject()}
              >
                <Button size="small" danger loading={deletingProject}>
                  {t("common.delete", "Delete")}
                </Button>
              </Popconfirm>
            </>
          ) : null}
          <Button size="small" onClick={() => void loadAgents()} loading={loading}>
            {t("common.refresh", "Refresh")}
          </Button>
        </div>
      </div>

      {error && <Alert type="error" showIcon message={error} />}

      <div className={styles.workspaceInfo}>
        <p className={styles.workspacePath}>
          {t("projects.workspacePath", "Workspace Path")}: {" "}
          {selectedProject?.workspace_dir ||
            currentAgent?.workspace_dir ||
            t("projects.noAgent", "No agent is currently available.")}
        </p>
      </div>

      {loading && !currentAgent ? (
        <div className={styles.centerState}>
          <Spin />
        </div>
      ) : !currentAgent ? (
        <Empty description={t("projects.noAgent", "No agent is currently available.")} />
      ) : projects.length === 0 ? (
        <Empty description={t("projects.noProjects", "No projects in this workspace yet.")} />
      ) : !selectedProject ? (
        <Card>
          <Empty
            description={t("projects.notFound", "Project not found in current workspace")}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button onClick={() => navigate("/projects")}>
              {t("projects.backToList", "Back to project list")}
            </Button>
          </Empty>
        </Card>
      ) : (
        <div className={styles.content}>
          <div className={styles.columnMiddle}>
            <Card
              title={<span className={styles.sectionTitle}>{t("projects.pipeline.title", "Pipeline")}</span>}
              styles={{ body: { padding: 12 } }}
              extra={
                <Text type="secondary" className={styles.panelExtraText}>
                  {selectedRunSummary?.status || t("projects.pipeline.noRun", "No run")}
                </Text>
              }
            >
              <div className={styles.scrollContainer}>
                <div className={styles.pipelineTopActions}>
                  <Button size="small" onClick={() => navigate("/projects")}>
                    {t("projects.backToList", "Back to project list")}
                  </Button>
                  <Button size="small" onClick={() => setUploadModalOpen(true)}>
                    {t("projects.upload.button", "Upload Files")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => void handleOpenImportModal()}
                    loading={importLoading && !importModalOpen}
                  >
                    {t("projects.pipeline.importGlobal", "Import Global")}
                  </Button>
                </div>

                <div className={styles.runToolbar}>
                  <Select
                    size="small"
                    className={styles.templateSelect}
                    value={selectedTemplateId || undefined}
                    placeholder={t("projects.pipeline.template", "Select template")}
                    options={pipelineTemplates.map((template) => ({
                      label: `${template.name}${template.version ? ` (${template.version})` : ""}`,
                      value: template.id,
                    }))}
                    onChange={setSelectedTemplateId}
                  />
                  <Button
                    size="small"
                    type="primary"
                    className={styles.runButton}
                    disabled={!selectedTemplateId || !selectedProject}
                    loading={createRunLoading}
                    onClick={() => void handleCreateRun()}
                  >
                    {t("projects.pipeline.run", "Run")}
                  </Button>
                </div>

                <div className={styles.progressCoach}>
                  <div className={styles.progressCoachMeta}>
                    <div className={styles.subSectionTitle}>
                      {t("projects.pipeline.dialogueDriven", "Dialogue-Driven Build")}
                    </div>
                    <div className={styles.itemMeta}>{verificationGateSummary}</div>
                  </div>
                  <div className={styles.progressCoachActions}>
                    <Button size="small" onClick={() => void handlePrepareImplementationDraft()}>
                      {t("projects.pipeline.nextImplementation", "Prepare next implementation prompt")}
                    </Button>
                    <Button size="small" onClick={() => void handlePrepareValidationDraft()}>
                      {t("projects.pipeline.nextValidation", "Prepare validation prompt")}
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      disabled={!canPromoteToTemplateDraft || !selectedTemplateId || !selectedRunId}
                      onClick={() => void handlePreparePromotionDraft()}
                    >
                      {t("projects.pipeline.promoteDraft", "Prepare promotion-to-template prompt")}
                    </Button>
                  </div>
                </div>

                {pipelineLoading ? (
                  <div className={styles.centerState}>
                    <Spin />
                  </div>
                ) : (
                  <>
                    <div className={styles.runList}>
                      {runsForSelectedTemplate.length === 0 ? (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t(
                            "projects.pipeline.noRunsForFlow",
                            "No runs for selected flow yet",
                          )}
                        />
                      ) : (
                        <Collapse
                          accordion
                          ghost
                          activeKey={selectedRunId || undefined}
                          onChange={(activeKey) => {
                            const key = Array.isArray(activeKey) ? activeKey[0] : activeKey;
                            setSelectedRunId(typeof key === "string" ? key : "");
                          }}
                          items={runsForSelectedTemplate.map((run) => ({
                            key: run.id,
                            label: (
                              <div className={styles.itemTitleRow}>
                                <span className={styles.itemTitle}>
                                  {t("projects.pipeline.runStartedAt", "Run @ {{time}}", {
                                    time: formatRunTimeLabel(run.created_at),
                                  })}
                                </span>
                                <Tag color={statusTagColor(run.status)}>{run.status}</Tag>
                              </div>
                            ),
                            children: (
                              <div className={styles.runAccordionBody}>
                                <div className={styles.itemMeta}>{run.id}</div>
                                <div className={styles.itemMeta}>{run.template_id}</div>
                                <div className={styles.itemMeta}>{run.updated_at}</div>
                                {selectedRunId === run.id && runDetail ? (
                                  <>
                                    <div className={styles.subSectionTitle}>
                                      {t("projects.pipeline.steps", "Steps")}
                                    </div>
                                    <div className={styles.progressLine}>
                                      {t("projects.pipeline.progress", "Progress")}: {runProgress.completed}/
                                      {runProgress.total} · running {runProgress.running} · pending {runProgress.pending}
                                    </div>
                                    {runDetail.steps.length > 0 ? (
                                      runDetail.steps.map((step) => {
                                        const contract = stepContractById.get(step.id);
                                        const dependsOn = (contract?.depends_on || []).filter(Boolean);
                                        const inputKeys = Object.keys(contract?.inputs || {});
                                        const outputKeys = Object.keys(contract?.outputs || {});
                                        const bindingKeys = Object.keys(contract?.input_bindings || {});
                                        const hasPrompt = Boolean((contract?.prompt || "").trim());
                                        const hasScript = Boolean((contract?.script || "").trim());
                                        const retryMaxAttempts =
                                          typeof contract?.retry_policy?.max_attempts === "number"
                                            ? String(contract.retry_policy.max_attempts)
                                            : "-";

                                        const stepSelected = selectedStepId === step.id;
                                        const stepRelated = !stepSelected && highlightedStepIds.has(step.id);

                                        return (
                                          <button
                                            key={step.id}
                                            type="button"
                                            className={`${styles.stepItem} ${stepSelected ? styles.selected : ""} ${stepRelated ? styles.related : ""}`}
                                            onClick={() => handleSelectStep(step.id)}
                                          >
                                            <div className={styles.itemTitleRow}>
                                              <span className={styles.itemTitle}>{step.name}</span>
                                              <Tag color={statusTagColor(step.status)}>{step.status}</Tag>
                                            </div>
                                            <div className={styles.itemMeta}>{step.kind}</div>
                                            <div className={styles.itemMeta}>{step.id}</div>
                                            <div className={styles.itemMeta}>
                                              {t("projects.pipeline.contract.dependsOn", "Depends on")}: {dependsOn.join(", ") || "-"}
                                            </div>
                                            <div className={styles.itemMeta}>
                                              {t("projects.pipeline.contract.inputs", "Inputs")}: {inputKeys.join(", ") || "-"}
                                            </div>
                                            <div className={styles.itemMeta}>
                                              {t("projects.pipeline.contract.outputs", "Outputs")}: {outputKeys.join(", ") || "-"}
                                            </div>
                                            <div className={styles.itemMeta}>
                                              {t("projects.pipeline.contract.bindings", "Input bindings")}: {bindingKeys.join(", ") || "-"}
                                            </div>
                                            <div className={styles.itemMeta}>
                                              {t("projects.pipeline.contract.execution", "Execution")}: {hasPrompt ? "prompt" : "-"}
                                              {hasScript ? "+script" : ""}
                                            </div>
                                            <div className={styles.itemMeta}>
                                              {t("projects.pipeline.contract.retry", "Retry max attempts")}: {retryMaxAttempts}
                                            </div>
                                          </button>
                                        );
                                      })
                                    ) : (
                                      <Empty
                                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                                        description={t("projects.pipeline.noSteps", "No steps available")}
                                      />
                                    )}
                                  </>
                                ) : (
                                  <div className={styles.itemMeta}>
                                    {t(
                                      "projects.pipeline.expandToViewSteps",
                                      "Expand selected run to view step records",
                                    )}
                                  </div>
                                )}
                              </div>
                            ),
                          }))}
                        />
                      )}
                    </div>

                    {runsForSelectedTemplate.length === 0 && (
                      <div className={styles.stepPanel}>
                        <div className={styles.subSectionTitle}>
                          {t("projects.pipeline.steps", "Steps")}
                        </div>
                        {activeRunTemplate?.steps && activeRunTemplate.steps.length > 0 ? (
                        activeRunTemplate.steps.map((step) => {
                          const dependsOn = (step.depends_on || []).filter(Boolean);
                          const inputKeys = Object.keys(step.inputs || {});
                          const outputKeys = Object.keys(step.outputs || {});
                          const bindingKeys = Object.keys(step.input_bindings || {});
                          const hasPrompt = Boolean((step.prompt || "").trim());
                          const hasScript = Boolean((step.script || "").trim());
                          const retryMaxAttempts =
                            typeof step.retry_policy?.max_attempts === "number"
                              ? String(step.retry_policy.max_attempts)
                              : "-";

                          const stepSelected = selectedStepId === step.id;
                          const stepRelated = !stepSelected && highlightedStepIds.has(step.id);

                          return (
                            <button
                              key={step.id}
                              type="button"
                              className={`${styles.stepItem} ${stepSelected ? styles.selected : ""} ${stepRelated ? styles.related : ""}`}
                              onClick={() => handleSelectStep(step.id)}
                            >
                              <div className={styles.itemTitleRow}>
                                <span className={styles.itemTitle}>{step.name}</span>
                                <Tag color="blue">{t("projects.pipeline.templateStep", "template")}</Tag>
                              </div>
                              <div className={styles.itemMeta}>{step.kind}</div>
                              <div className={styles.itemMeta}>{step.id}</div>
                              <div className={styles.itemMeta}>
                                {t("projects.pipeline.contract.dependsOn", "Depends on")}: {dependsOn.join(", ") || "-"}
                              </div>
                              <div className={styles.itemMeta}>
                                {t("projects.pipeline.contract.inputs", "Inputs")}: {inputKeys.join(", ") || "-"}
                              </div>
                              <div className={styles.itemMeta}>
                                {t("projects.pipeline.contract.outputs", "Outputs")}: {outputKeys.join(", ") || "-"}
                              </div>
                              <div className={styles.itemMeta}>
                                {t("projects.pipeline.contract.bindings", "Input bindings")}: {bindingKeys.join(", ") || "-"}
                              </div>
                              <div className={styles.itemMeta}>
                                {t("projects.pipeline.contract.execution", "Execution")}: {hasPrompt ? "prompt" : "-"}
                                {hasScript ? "+script" : ""}
                              </div>
                              <div className={styles.itemMeta}>
                                {t("projects.pipeline.contract.retry", "Retry max attempts")}: {retryMaxAttempts}
                              </div>
                            </button>
                          );
                        })
                        ) : (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("projects.pipeline.noSteps", "No steps available")}
                          />
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </Card>

            <Modal
              title={t("projects.upload.title", "Upload Project Files")}
              open={uploadModalOpen}
              width={760}
              confirmLoading={uploadingFiles}
              onOk={() => void handleUploadFiles()}
              onCancel={() => setUploadModalOpen(false)}
              okButtonProps={{ disabled: pendingUploads.length === 0 }}
              okText={t("projects.upload.confirm", "Upload")}
            >
              <div className={styles.uploadModalBody}>
                <Input
                  value={uploadTargetDir}
                  onChange={(event) => setUploadTargetDir(event.target.value)}
                  placeholder={t("projects.upload.targetDir", "Target directory (default: data)")}
                />
                <Dragger
                  className={styles.uploadDragger}
                  multiple
                  beforeUpload={(file) => {
                    setPendingUploads((prev) => {
                      const exists = prev.some((item) => item.name === file.name && item.size === file.size);
                      return exists ? prev : [...prev, file as File];
                    });
                    return false;
                  }}
                  onRemove={(file) => {
                    setPendingUploads((prev) => prev.filter((item) => !(item.name === file.name && item.size === file.size)));
                    return true;
                  }}
                  fileList={pendingUploads.map((file, index) => ({
                    uid: `${file.name}-${file.size}-${index}`,
                    name: file.name,
                    status: "done" as const,
                    size: file.size,
                    type: file.type,
                  }))}
                >
                  <p>{t("projects.upload.dragHint", "Drag files here or click to select")}</p>
                </Dragger>
              </div>
            </Modal>

            <Modal
              title={t("projects.pipeline.importGlobalTitle", "Import Global Pipeline")}
              open={importModalOpen}
              confirmLoading={importLoading}
              onOk={() => void handleImportPlatformTemplate()}
              onCancel={() => setImportModalOpen(false)}
              okButtonProps={{ disabled: !selectedPlatformTemplateId }}
              okText={t("projects.pipeline.importGlobal", "Import Global")}
            >
              {platformTemplates.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t(
                    "projects.pipeline.noGlobalTemplates",
                    "No global templates available",
                  )}
                />
              ) : (
                <Select
                  className={styles.importTemplateSelect}
                  value={selectedPlatformTemplateId || undefined}
                  options={platformTemplates.map((template) => ({
                    label: `${template.name}${template.version ? ` (${template.version})` : ""}`,
                    value: template.id,
                  }))}
                  onChange={setSelectedPlatformTemplateId}
                />
              )}
            </Modal>
          </div>

          <div className={styles.columnRight}>
            <Card
              style={{
                height: "100%",
                display: "flex",
                flexDirection: "column",
                minHeight: 0,
                overflow: "hidden",
              }}
              title={
                <span className={styles.sectionTitle}>{t("projects.preview", "Workbench")}</span>
              }
              styles={{
                body: {
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  minHeight: 0,
                  overflow: "hidden",
                },
              }}
              extra={
                <Text type="secondary" className={styles.panelExtraText}>
                  {selectedProject?.id || routeProjectId}
                </Text>
              }
            >
              <Tabs
                className={styles.rightTabs}
                items={[
                  {
                    key: "artifacts",
                    label: t("projects.artifacts", "Artifacts"),
                    children: (
                      <div className={`${styles.previewBody} ${styles.previewBodyArtifacts}`}>
                        {filesLoading ? (
                          <div className={styles.centerState}>
                            <Spin />
                          </div>
                        ) : artifactRecords.length === 0 ? (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("projects.noFiles", "No files in this project")}
                          />
                        ) : (
                          <div className={styles.artifactPanel}>
                            <div className={styles.artifactList}>
                              <div className={styles.artifactToolbar}>
                                <div className={styles.itemMeta}>
                                  {t("projects.artifacts.hideBuiltins", "Hide built-in files")}
                                </div>
                                <Switch
                                  size="small"
                                  checked={hideBuiltInFiles}
                                  onChange={setHideBuiltInFiles}
                                />
                              </div>
                              {(selectedStepId || selectedArtifactRecord) && (
                                <div className={styles.focusBar}>
                                  <div className={styles.itemMeta}>
                                    {selectedStepId
                                      ? t("projects.artifacts.filteredByStep", "Filtered by step: {{stepId}}", {
                                          stepId: selectedStepId,
                                        })
                                      : selectedArtifactRecord
                                        ? t("projects.artifacts.focusedArtifact", "Focused artifact relation")
                                        : ""}
                                  </div>
                                  <Button
                                    size="small"
                                    onClick={() => {
                                      setSelectedStepId("");
                                      setSelectedFilePath("");
                                    }}
                                  >
                                    {t("common.clear", "Clear")}
                                  </Button>
                                </div>
                              )}
                              {groupedArtifactRecords.map((group) => (
                                <div key={group.key} className={styles.artifactGroup}>
                                  <div className={styles.artifactGroupTitle}>{group.title}</div>
                                  {group.items.map((item) => {
                                    const selected = item.path === selectedFilePath;
                                    const artifactRelated =
                                      Boolean(selectedStepId) && relatedArtifactPathsForSelectedStep.has(item.path);
                                    const fileInfo = projectFiles.find((file) => file.path === item.path);
                                    return (
                                      <div
                                        key={item.artifact_id}
                                        role="button"
                                        tabIndex={0}
                                        className={`${styles.listItem} ${selected ? styles.selected : ""} ${artifactRelated && !selected ? styles.related : ""}`}
                                        onClick={() => {
                                          void handleSelectArtifactFile(item.path);
                                        }}
                                        onKeyDown={(event) => {
                                          if (event.key === "Enter" || event.key === " ") {
                                            event.preventDefault();
                                            void handleSelectArtifactFile(item.path);
                                          }
                                        }}
                                      >
                                        <div className={styles.itemTitleRow}>
                                          <div className={styles.itemTitleMain}>
                                            <div className={styles.itemTitle}>{item.name}</div>
                                          </div>
                                          <div className={styles.itemActions}>
                                            <Tag color={
                                              item.kind === "source"
                                                ? "default"
                                                : item.kind === "final"
                                                  ? "success"
                                                  : "processing"
                                            }>
                                              {item.kind}
                                            </Tag>
                                          </div>
                                        </div>
                                        <div className={styles.itemMeta}>{item.path}</div>
                                        <div className={styles.itemMeta}>
                                          {item.producer_step_name
                                            ? t("projects.artifacts.producedBy", "Produced by: {{step}}", {
                                                step: item.producer_step_name,
                                              })
                                            : t("projects.artifacts.originalFile", "Original project file")}
                                        </div>
                                        {fileInfo && (
                                          <div className={styles.itemMeta}>
                                            {formatBytes(fileInfo.size)} · {fileInfo.modified_time}
                                          </div>
                                        )}
                                        <div className={styles.listItemFooter}>
                                          <Button
                                            size="small"
                                            type="text"
                                            icon={selectedAttachPaths.includes(item.path) ? <MinusOutlined /> : <PlusOutlined />}
                                            className={styles.attachActionButton}
                                            onClick={(event) => {
                                              event.stopPropagation();
                                              void handleAttachArtifactToChat(item.path);
                                            }}
                                          />
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              ))}
                            </div>
                            <div className={styles.previewPane}>
                              {contentLoading ? (
                                <div className={styles.centerState}>
                                  <Spin />
                                </div>
                              ) : selectedFilePath ? (
                                <>
                                  {selectedArtifactRecord && (
                                    <div className={styles.artifactDetailCard}>
                                      <div className={styles.itemTitleRow}>
                                        <div className={styles.itemTitle}>{selectedArtifactRecord.name}</div>
                                        <Tag color={
                                          selectedArtifactRecord.kind === "source"
                                            ? "default"
                                            : selectedArtifactRecord.kind === "final"
                                              ? "success"
                                              : "processing"
                                        }>
                                          {selectedArtifactRecord.kind}
                                        </Tag>
                                      </div>
                                      <div className={styles.itemMeta}>{selectedArtifactRecord.path}</div>
                                      <div className={styles.itemMeta}>
                                        {selectedArtifactRecord.producer_step_name
                                          ? t("projects.artifacts.producedBy", "Produced by: {{step}}", {
                                              step: selectedArtifactRecord.producer_step_name,
                                            })
                                          : t("projects.artifacts.originalFile", "Original project file")}
                                      </div>
                                      <div className={styles.itemMeta}>
                                        {t("projects.artifacts.consumedBy", "Consumed by")}: {selectedArtifactRecord.consumer_step_names.join(", ") || "-"}
                                      </div>
                                      <div className={styles.lineageRow}>
                                        <span className={styles.lineageLabel}>
                                          {t("projects.artifacts.lineage", "Lineage")}
                                        </span>
                                        <div className={styles.lineageFlow}>
                                          {selectedArtifactRecord.producer_step_name ? (
                                            <button
                                              type="button"
                                              className={styles.lineageNode}
                                              onClick={() => handleSelectStep(selectedArtifactRecord.producer_step_id || "")}
                                            >
                                              {selectedArtifactRecord.producer_step_name}
                                            </button>
                                          ) : (
                                            <span className={styles.lineageTerminal}>
                                              {t("projects.artifacts.sourceTerminal", "Project Source")}
                                            </span>
                                          )}
                                          <span className={styles.lineageArrow}>-&gt;</span>
                                          <span className={styles.lineageArtifact}>{selectedArtifactRecord.name}</span>
                                          <span className={styles.lineageArrow}>-&gt;</span>
                                          {selectedArtifactRecord.consumer_step_names.length > 0 ? (
                                            <div className={styles.lineageConsumerList}>
                                              {selectedArtifactRecord.consumer_step_names.map((consumerName, index) => (
                                                <button
                                                  key={`${selectedArtifactRecord.artifact_id}-${consumerName}`}
                                                  type="button"
                                                  className={styles.lineageNode}
                                                  onClick={() => handleSelectStep(selectedArtifactRecord.consumer_step_ids[index] || "")}
                                                >
                                                  {consumerName}
                                                </button>
                                              ))}
                                            </div>
                                          ) : (
                                            <span className={styles.lineageTerminal}>
                                              {t("projects.artifacts.finalTerminal", "Terminal Output")}
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  )}
                                  <pre className={styles.previewContent}>{fileContent}</pre>
                                </>
                              ) : (
                                <Empty
                                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                                  description={t("projects.selectFile", "Select a file to preview")}
                                />
                              )}
                            </div>
                            {selectedAttachPaths.length > 0 && (
                              <div className={styles.attachFloatingBar}>
                                <div className={styles.attachCountText}>
                                  {t("projects.chat.selectedCount", "Selected files: {{count}}", {
                                    count: selectedAttachPaths.length,
                                  })}
                                </div>
                                <Checkbox
                                  className={styles.attachAutoAnalyzeCheck}
                                  checked={autoAnalyzeOnAttach}
                                  onChange={(event) => setAutoAnalyzeOnAttach(event.target.checked)}
                                >
                                  {t("projects.chat.autoAnalyze", "Auto Analyze")}
                                </Checkbox>
                                <Button
                                  type="primary"
                                  size="small"
                                  icon={<SendOutlined />}
                                  loading={sendingSelectedFiles}
                                  onClick={() => void handleSendSelectedFilesToChat()}
                                >
                                  {t("projects.chat.sendSelected", "Attach To Chat")}
                                </Button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ),
                  },
                  {
                    key: "metrics",
                    label: t("projects.metrics", "Metrics"),
                    children: (
                      <div className={styles.previewBody}>
                        {!runDetail ? (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("projects.pipeline.noRun", "No run")}
                          />
                        ) : (
                          <div className={styles.metricPanel}>
                            <div className={styles.metricSummaryGrid}>
                              <div className={styles.metricSummaryCard}>
                                <div className={styles.itemMeta}>Total Steps</div>
                                <div className={styles.metricSummaryValue}>{runProgress.total}</div>
                              </div>
                              <div className={styles.metricSummaryCard}>
                                <div className={styles.itemMeta}>Completed</div>
                                <div className={styles.metricSummaryValue}>{runProgress.completed}</div>
                              </div>
                              <div className={styles.metricSummaryCard}>
                                <div className={styles.itemMeta}>Running</div>
                                <div className={styles.metricSummaryValue}>{runProgress.running}</div>
                              </div>
                              <div className={styles.metricSummaryCard}>
                                <div className={styles.itemMeta}>Pending</div>
                                <div className={styles.metricSummaryValue}>{runProgress.pending}</div>
                              </div>
                            </div>
                            {runDetail.steps.map((step) => {
                              const entries = Object.entries(step.metrics || {});
                              return (
                                <div key={step.id} className={styles.metricBlock}>
                                  <div className={styles.itemTitleRow}>
                                    <span className={styles.itemTitle}>{step.name}</span>
                                    <Tag color={statusTagColor(step.status)}>{step.status}</Tag>
                                  </div>
                                  {entries.length === 0 ? (
                                    <div className={styles.itemMeta}>No metrics</div>
                                  ) : (
                                    entries.map(([key, value]) => (
                                      <div key={key} className={styles.itemMeta}>
                                        {key}: {String(value)}
                                      </div>
                                    ))
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    ),
                  },
                  {
                    key: "evidence",
                    label: t("projects.evidence", "Evidence"),
                    children: (
                      <div className={styles.previewBody}>
                        {!runDetail ? (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("projects.pipeline.noRun", "No run")}
                          />
                        ) : (
                          <div className={styles.metricPanel}>
                            {runDetail.steps.map((step) => (
                              <div key={step.id} className={styles.metricBlock}>
                                <div className={styles.itemTitle}>{step.name}</div>
                                {step.evidence.length === 0 ? (
                                  <div className={styles.itemMeta}>No evidence</div>
                                ) : (
                                  step.evidence.map((item) => (
                                    <div key={`${step.id}-${item}`} className={styles.itemMeta}>
                                      {item}
                                    </div>
                                  ))
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ),
                  },
                ]}
              />
            </Card>
          </div>

          <div className={styles.columnChat}>
            <Card
              style={{
                height: "100%",
                display: "flex",
                flexDirection: "column",
                minHeight: 0,
                overflow: "hidden",
              }}
              title={<span className={styles.sectionTitle}>{t("projects.chat", "Chat")}</span>}
              styles={{
                body: {
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  flex: 1,
                  minHeight: 0,
                  overflow: "hidden",
                },
              }}
              extra={
                <Text type="secondary" className={styles.panelExtraText}>
                  {selectedRunId || t("projects.pipeline.noRun", "No run")}
                </Text>
              }
            >
              <div className={styles.previewBody}>
                {!selectedRunId ? (
                  chatStarting ? (
                    <div className={styles.centerState}>
                      <Spin />
                    </div>
                  ) : activeDesignChatId ? (
                    <div className={styles.chatPanel}>
                      <AnywhereChat
                        sessionId={activeDesignChatId}
                        autoAttachRequest={autoAttachRequest}
                        onAutoAttachHandled={(payload) => {
                          if (!payload.ok) {
                            message.error(
                              t("projects.chat.autoAttachFailed", "Failed to attach selected file to chat."),
                            );
                          }
                          setAutoAttachRequest((prev) => (prev?.id === payload.id ? null : prev));
                        }}
                        onNewChat={() => {
                          void handleEnsureDesignChat(true);
                        }}
                        inputPlaceholder={t(
                          "projects.chat.designPlaceholder",
                          "Describe your target workflow and constraints, and I will draft/refine the project flow.",
                        )}
                        welcomeGreeting={t(
                          "projects.chat.designWelcomeGreeting",
                          "Project flow design assistant is ready.",
                        )}
                        welcomeDescription={t(
                          "projects.chat.designWelcomeDescription",
                          "Use this session to build a flow draft from your real project files before launching a run.",
                        )}
                        welcomePrompts={[
                          t(
                            "projects.chat.designPrompt1",
                            "Based on the current source files, propose a 4-step flow with clear inputs and outputs.",
                          ),
                          t(
                            "projects.chat.designPrompt2",
                            "Please optimize the flow for reliability and add retry policy suggestions.",
                          ),
                        ]}
                      />
                    </div>
                  ) : (
                    <div className={styles.chatEmptyAction}>
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={t(
                          "projects.chat.selectRun",
                          "Select a run, or start a flow design session first.",
                        )}
                      >
                        <Button type="primary" onClick={() => void handleEnsureDesignChat()}>
                          {t("projects.chat.startDesign", "Start flow design")}
                        </Button>
                      </Empty>
                    </div>
                  )
                ) : chatStarting ? (
                  <div className={styles.centerState}>
                    <Spin />
                  </div>
                ) : activeRunChatId ? (
                  <div className={styles.chatPanel}>
                    <AnywhereChat
                      sessionId={activeRunChatId}
                      autoAttachRequest={autoAttachRequest}
                      onAutoAttachHandled={(payload) => {
                        if (!payload.ok) {
                          message.error(
                            t("projects.chat.autoAttachFailed", "Failed to attach selected file to chat."),
                          );
                        }
                        setAutoAttachRequest((prev) => (prev?.id === payload.id ? null : prev));
                      }}
                      onNewChat={() => {
                        void handleEnsureRunChat(true);
                      }}
                      inputPlaceholder={t(
                        "projects.chat.placeholder",
                        "Describe what you want to adjust in this run, and I will help iterate.",
                      )}
                      welcomeGreeting={t(
                        "projects.chat.welcomeGreeting",
                        "Project run assistant is ready.",
                      )}
                      welcomeDescription={t(
                        "projects.chat.welcomeDescription",
                        "Discuss artifacts, metrics, and evidence for the selected run without leaving this page.",
                      )}
                      welcomePrompts={[
                        t(
                          "projects.chat.prompt1",
                          "Summarize the risks in this run and suggest next actions.",
                        ),
                        t(
                          "projects.chat.prompt2",
                          "Based on current evidence, propose a retry strategy for failed steps.",
                        ),
                      ]}
                    />
                  </div>
                ) : (
                  <div className={styles.chatEmptyAction}>
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={t(
                        "projects.chat.noSession",
                        "No chat session for this run yet",
                      )}
                    >
                      <Button type="primary" onClick={() => void handleEnsureRunChat()}>
                        {t("projects.chat.start", "Start chat")}
                      </Button>
                    </Empty>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
