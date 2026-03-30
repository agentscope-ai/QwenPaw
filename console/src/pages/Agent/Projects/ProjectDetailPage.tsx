import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Modal,
  Select,
  Spin,
  Tag,
  Tabs,
  Typography,
  message,
} from "antd";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import { chatApi } from "../../../api/modules/chat";
import AnywhereChat from "../../../components/AnywhereChat";
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

export default function ProjectDetailPage() {
  const { t } = useTranslation();
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
  const [chatStarting, setChatStarting] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState("");
  const runFocusChatIdRef = useRef("");

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

  const artifactRecords = useMemo<ProjectPipelineArtifactRecord[]>(() => {
    if (runDetail?.artifact_records?.length) {
      return runDetail.artifact_records.filter((item) => isPreviewablePath(item.path));
    }

    return projectFiles
      .filter((file) => isPreviewablePath(file.path))
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
  }, [projectFiles, runDetail?.artifact_records, selectedRunId]);

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

  const handleEnsureRunChat = useCallback(async (forceNew = false) => {
    if (!selectedProject || !selectedRunId) {
      return;
    }

    if (!forceNew && activeRunChatId) {
      return;
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
    } catch (err) {
      console.error("failed to create project run chat", err);
      setError(t("projects.chat.startFailed", "Failed to start project chat."));
    } finally {
      setChatStarting(false);
    }
  }, [activeRunChatId, resolvedProjectRequestId, selectedProject, selectedRunId, t]);

  useEffect(() => {
    runFocusChatIdRef.current = runFocusChatId;
  }, [runFocusChatId]);

  useEffect(() => {
    const fallbackChatId = runDetail?.focus_chat_id || selectedRunSummary?.focus_chat_id || "";
    if (fallbackChatId && fallbackChatId !== runFocusChatId) {
      setRunFocusChatId(fallbackChatId);
    }
  }, [runDetail?.focus_chat_id, runFocusChatId, selectedRunSummary?.focus_chat_id]);

  useEffect(() => {
    return () => {
      const chatId = runFocusChatIdRef.current;
      if (chatId) {
        void chatApi
          .clearChatMeta(chatId, {
            user_id: "default",
            channel: "console",
          })
          .catch(() => {});
      }
    };
  }, []);

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
  }, [routeProjectId]);

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
    if (!currentAgent || !selectedProject) {
      return;
    }
    void loadProjectFiles(currentAgent.id, selectedProject);
    void loadPipelineContext(currentAgent.id, selectedProject);
  }, [currentAgent, selectedProject, loadProjectFiles, loadPipelineContext]);

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
        <Button size="small" onClick={() => void loadAgents()} loading={loading}>
          {t("common.refresh", "Refresh")}
        </Button>
      </div>

      {error && <Alert type="error" showIcon message={error} />}

      <div className={styles.workspaceInfo}>
        <p className={styles.workspacePath}>
          {t("projects.workspacePath", "Workspace Path")}: {" "}
          {currentAgent?.workspace_dir ||
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
              title={
                <span className={styles.sectionTitle}>{t("projects.preview", "Workbench")}</span>
              }
              styles={{ body: { padding: 0 } }}
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
                      <div className={styles.previewBody}>
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
                                      <button
                                        key={item.artifact_id}
                                        type="button"
                                        className={`${styles.listItem} ${selected ? styles.selected : ""} ${artifactRelated && !selected ? styles.related : ""}`}
                                        onClick={() => setSelectedFilePath(item.path)}
                                      >
                                        <div className={styles.itemTitleRow}>
                                          <div className={styles.itemTitle}>{item.name}</div>
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
                                      </button>
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
              title={<span className={styles.sectionTitle}>{t("projects.chat", "Chat")}</span>}
              styles={{ body: { padding: 0 } }}
              extra={
                <Text type="secondary" className={styles.panelExtraText}>
                  {selectedRunId || t("projects.pipeline.noRun", "No run")}
                </Text>
              }
            >
              <div className={styles.previewBody}>
                {!selectedRunId ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t(
                      "projects.chat.selectRun",
                      "Select a pipeline run first to open chat",
                    )}
                  />
                ) : chatStarting ? (
                  <div className={styles.centerState}>
                    <Spin />
                  </div>
                ) : activeRunChatId ? (
                  <div className={styles.chatPanel}>
                    <AnywhereChat
                      sessionId={activeRunChatId}
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
