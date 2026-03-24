import { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Modal, Select, Spin, Tag, Typography, message } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "../../../api/modules/agents";
import { chatApi } from "../../../api/modules/chat";
import AnywhereChat from "../../../components/AnywhereChat";
import sessionApi from "../../Chat/sessionApi";
import {
  buildPipelineDesignBootstrapPrompt,
  buildPipelineDesignChatPath,
} from "../../../utils/pipelineDesign";
import { trackNavigation } from "../../../utils/navigationTelemetry";
import type {
  AgentProjectSummary,
  AgentSummary,
  ProjectPipelineRunSummary,
  ProjectPipelineTemplateInfo,
} from "../../../api/types/agents";
import { useAgentStore } from "../../../stores/agentStore";
import styles from "./index.module.less";

const { Title, Text } = Typography;

type TemplateItem = ProjectPipelineTemplateInfo & {
  projectId: string;
  projectName: string;
};

type RunItem = ProjectPipelineRunSummary & {
  projectId: string;
  projectName: string;
};

type PipelineManagementData = {
  templates: TemplateItem[];
  runs: RunItem[];
};

type PipelineGroup = {
  key: string;
  id: string;
  name: string;
  description: string;
  versions: ProjectPipelineTemplateInfo[];
  projects: { id: string; name: string }[];
  source: "independent" | "project";
};

type StepDiffItem = {
  id: string;
  kind: "added" | "removed" | "changed" | "unchanged";
  current?: { name: string; kind: string; description: string };
  compare?: { name: string; kind: string; description: string };
  changedFields: string[];
};

type EditChatTarget = {
  pipelineId: string;
  pipelineName: string;
  version: string;
  isEmptyNodes: boolean;
};

const INDEPENDENT_PIPELINE_SCOPE_ID = "__independent__";

function getTemplateSourceKind(item: TemplateItem): "independent" | "project" {
  return item.projectId === INDEPENDENT_PIPELINE_SCOPE_ID ? "independent" : "project";
}

function buildPipelineGroupKey(
  templateId: string,
  source: "independent" | "project",
): string {
  return `${templateId}::${source}`;
}

async function loadPipelineManagementData(
  agentId: string,
  projectList: AgentProjectSummary[],
  independentScopeLabel: string,
): Promise<PipelineManagementData> {
  const [perProject, agentTemplates] = await Promise.all([
    Promise.all(
      projectList.map(async (project) => {
        const [templatesResult, runsResult] = await Promise.allSettled([
          agentsApi.listProjectPipelineTemplates(agentId, project.id),
          agentsApi.listProjectPipelineRuns(agentId, project.id),
        ]);

        return {
          project,
          templates:
            templatesResult.status === "fulfilled"
              ? templatesResult.value
              : [],
          runs: runsResult.status === "fulfilled" ? runsResult.value : [],
        };
      }),
    ),
    agentsApi.listAgentPipelineTemplates(agentId).catch(() => []),
  ]);

  const templates: TemplateItem[] = [
    ...agentTemplates.map((tpl) => ({
      ...tpl,
      projectId: INDEPENDENT_PIPELINE_SCOPE_ID,
      projectName: independentScopeLabel,
    })),
    ...perProject.flatMap((item) =>
      item.templates.map((tpl) => ({
        ...tpl,
        projectId: item.project.id,
        projectName: item.project.name,
      })),
    ),
  ];

  const runs: RunItem[] = perProject
    .flatMap((item) =>
      item.runs.map((run) => ({
        ...run,
        projectId: item.project.id,
        projectName: item.project.name,
      })),
    )
    .sort((a, b) =>
      (b.updated_at || b.created_at).localeCompare(a.updated_at || a.created_at),
    );

  return { templates, runs };
}

function statusTagColor(status: string): string {
  switch (status) {
    case "running":
      return "processing";
    case "succeeded":
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

function getCurrentAgent(
  agents: AgentSummary[],
  selectedAgent: string,
): AgentSummary | undefined {
  return agents.find((agent) => agent.id === selectedAgent);
}

function buildPipelineEntrySessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `pipeline-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeVersion(version: string): string {
  return version.trim() || "0";
}

function compareSemverDesc(a: string, b: string): number {
  const parsePart = (value: string): number => {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
  };

  const partsA = normalizeVersion(a)
    .split(".")
    .map((part) => parsePart(part.replace(/[^0-9]/g, "")));
  const partsB = normalizeVersion(b)
    .split(".")
    .map((part) => parsePart(part.replace(/[^0-9]/g, "")));

  const length = Math.max(partsA.length, partsB.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (partsB[i] || 0) - (partsA[i] || 0);
    if (diff !== 0) return diff;
  }
  return normalizeVersion(b).localeCompare(normalizeVersion(a), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function stepComparable(step: { name: string; kind: string; description: string }): string {
  return `${step.name}|${step.kind}|${step.description}`;
}

function buildStepDiff(
  currentSteps: ProjectPipelineTemplateInfo["steps"],
  compareSteps: ProjectPipelineTemplateInfo["steps"],
): StepDiffItem[] {
  const currentMap = new Map(currentSteps.map((item) => [item.id, item]));
  const compareMap = new Map(compareSteps.map((item) => [item.id, item]));

  const result: StepDiffItem[] = [];

  currentSteps.forEach((step) => {
    const compareStep = compareMap.get(step.id);
    if (!compareStep) {
      result.push({
        id: step.id,
        kind: "added",
        current: {
          name: step.name,
          kind: step.kind,
          description: step.description,
        },
        changedFields: [],
      });
      return;
    }

    const changedFields: string[] = [];
    if (step.name !== compareStep.name) changedFields.push("name");
    if (step.kind !== compareStep.kind) changedFields.push("kind");
    if (step.description !== compareStep.description) changedFields.push("description");

    result.push({
      id: step.id,
      kind:
        stepComparable({
          name: step.name,
          kind: step.kind,
          description: step.description,
        }) ===
        stepComparable({
          name: compareStep.name,
          kind: compareStep.kind,
          description: compareStep.description,
        })
          ? "unchanged"
          : "changed",
      current: {
        name: step.name,
        kind: step.kind,
        description: step.description,
      },
      compare: {
        name: compareStep.name,
        kind: compareStep.kind,
        description: compareStep.description,
      },
      changedFields,
    });
  });

  compareSteps.forEach((step) => {
    if (currentMap.has(step.id)) return;
    result.push({
      id: step.id,
      kind: "removed",
      compare: {
        name: step.name,
        kind: step.kind,
        description: step.description,
      },
      changedFields: [],
    });
  });

  return result;
}

export default function PipelinesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { selectedAgent, agents, setAgents } = useAgentStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [selectedPipelineKey, setSelectedPipelineKey] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "independent" | "project">("all");
  const [selectedCurrentVersion, setSelectedCurrentVersion] = useState("");
  const [selectedCompareVersion, setSelectedCompareVersion] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [designChatStarting, setDesignChatStarting] = useState(false);
  const [draftSaving, setDraftSaving] = useState(false);
  const [designChatSessionId, setDesignChatSessionId] = useState("");
  const [editTargetKey, setEditTargetKey] = useState("");
  const [editGuidePlaceholder, setEditGuidePlaceholder] = useState("");
  const [editWelcomeMode, setEditWelcomeMode] = useState<"default" | "init">("default");
  const [draftPipelineKeys, setDraftPipelineKeys] = useState<string[]>([]);

  const currentAgent = useMemo(
    () => getCurrentAgent(agents, selectedAgent),
    [agents, selectedAgent],
  );

  const projects = useMemo<AgentProjectSummary[]>(
    () => currentAgent?.projects ?? [],
    [currentAgent?.projects],
  );

  const independentScopeLabel = t("pipelines.independentScope", "独立流程");

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      if (!selectedAgent) return;

      setLoading(true);
      setError("");

      try {
        let availableAgents = agents;
        if (availableAgents.length === 0) {
          const listResp = await agentsApi.listAgents();
          availableAgents = listResp.agents;
          if (mounted) setAgents(listResp.agents);
        }

        const agent = getCurrentAgent(availableAgents, selectedAgent);
        const projectList = agent?.projects ?? [];
        const data = await loadPipelineManagementData(
          selectedAgent,
          projectList,
          independentScopeLabel,
        );

        if (!mounted) return;

        setTemplates(data.templates);
        setRuns(data.runs);
      } catch (err) {
        console.error("failed to load pipeline management data", err);
        if (mounted) {
          setError(
            t(
              "pipelines.loadFailed",
              "Failed to load pipeline management data.",
            ),
          );
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    load();

    return () => {
      mounted = false;
    };
  }, [agents, independentScopeLabel, selectedAgent, setAgents, t]);

  const pipelineGroups = useMemo<PipelineGroup[]>(() => {
    const filteredTemplates = templates.filter((item) => {
      const isIndependent = item.projectId === INDEPENDENT_PIPELINE_SCOPE_ID;
      if (sourceFilter === "independent") return isIndependent;
      if (sourceFilter === "project") return !isIndependent;
      return true;
    });

    const map = new Map<string, TemplateItem[]>();
    filteredTemplates.forEach((item) => {
      const groupKey = buildPipelineGroupKey(item.id, getTemplateSourceKind(item));
      if (!map.has(groupKey)) {
        map.set(groupKey, []);
      }
      map.get(groupKey)?.push(item);
    });

    return Array.from(map.entries())
      .map(([groupKey, items]) => {
        const versionsByKey = new Map<string, ProjectPipelineTemplateInfo>();
        const projectMap = new Map<string, { id: string; name: string }>();

        items.forEach((item) => {
          const versionKey = normalizeVersion(item.version);
          if (!versionsByKey.has(versionKey)) {
            versionsByKey.set(versionKey, {
              id: item.id,
              name: item.name,
              version: item.version,
              description: item.description,
              steps: item.steps,
            });
          }
          if (!projectMap.has(item.projectId)) {
            projectMap.set(item.projectId, {
              id: item.projectId,
              name: item.projectName,
            });
          }
        });

        const versions = Array.from(versionsByKey.values()).sort((a, b) =>
          compareSemverDesc(a.version, b.version),
        );

        const source: PipelineGroup["source"] = getTemplateSourceKind(items[0]);

        return {
          key: groupKey,
          id: items[0].id,
          name: items[0].name,
          description: items[0].description,
          versions,
          projects: Array.from(projectMap.values()),
          source,
        };
      })
      .sort((a, b) => {
        const nameCmp = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
        if (nameCmp !== 0) return nameCmp;
        return a.source.localeCompare(b.source);
      });
  }, [sourceFilter, templates]);

  const selectedPipeline = useMemo(
    () => pipelineGroups.find((item) => item.key === selectedPipelineKey),
    [pipelineGroups, selectedPipelineKey],
  );

  const currentTemplate = useMemo(() => {
    if (!selectedPipeline) return null;
    return (
      selectedPipeline.versions.find(
        (item) => normalizeVersion(item.version) === selectedCurrentVersion,
      ) || selectedPipeline.versions[0] || null
    );
  }, [selectedCurrentVersion, selectedPipeline]);

  const compareTemplate = useMemo(() => {
    if (!selectedPipeline || !selectedCompareVersion) return null;
    return (
      selectedPipeline.versions.find(
        (item) => normalizeVersion(item.version) === selectedCompareVersion,
      ) || null
    );
  }, [selectedCompareVersion, selectedPipeline]);

  const selectedTemplateItem = useMemo(() => {
    if (!selectedPipeline || !selectedCurrentVersion) return null;
    return (
      templates.find(
        (item) =>
          item.id === selectedPipeline.id &&
          getTemplateSourceKind(item) === selectedPipeline.source &&
          normalizeVersion(item.version) === selectedCurrentVersion,
      ) || null
    );
  }, [selectedCurrentVersion, selectedPipeline, templates]);

  const selectedIsDraft = useMemo(() => {
    if (!selectedPipeline) return false;
    return draftPipelineKeys.includes(selectedPipeline.key);
  }, [draftPipelineKeys, selectedPipeline]);

  const hasUnsavedDrafts = draftPipelineKeys.length > 0;

  useEffect(() => {
    if (!hasUnsavedDrafts) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = t(
        "pipelines.unsavedLeaveWarning",
        "当前有未保存的流程草稿，离开后将丢失。",
      );
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [hasUnsavedDrafts, t]);

  const closeEditMode = () => {
    setEditMode(false);
    setEditGuidePlaceholder("");
    setEditWelcomeMode("default");
  };

  const requestCloseEditMode = () => {
    if (!selectedIsDraft) {
      closeEditMode();
      return;
    }

    Modal.confirm({
      title: t("pipelines.unsavedDraftTitle", "存在未保存草稿"),
      content: t(
        "pipelines.unsavedExitConfirm",
        "当前流程草稿尚未保存，退出编辑后改动可能丢失。是否继续？",
      ),
      okText: t("common.confirm", "确认"),
      cancelText: t("common.cancel", "取消"),
      onOk: () => {
        closeEditMode();
      },
    });
  };

  const requestSelectPipeline = (nextPipelineKey: string) => {
    if (!(editMode && selectedIsDraft && selectedPipelineKey !== nextPipelineKey)) {
      setSelectedPipelineKey(nextPipelineKey);
      setSelectedCompareVersion("");
      return;
    }

    Modal.confirm({
      title: t("pipelines.unsavedDraftTitle", "存在未保存草稿"),
      content: t(
        "pipelines.unsavedSwitchConfirm",
        "当前流程草稿尚未保存，切换流程后改动可能丢失。是否继续切换？",
      ),
      okText: t("common.confirm", "确认"),
      cancelText: t("common.cancel", "取消"),
      onOk: () => {
        closeEditMode();
        setSelectedPipelineKey(nextPipelineKey);
        setSelectedCompareVersion("");
      },
    });
  };

  const newVersionDiffItems = useMemo(
    () =>
      compareTemplate && currentTemplate
        ? buildStepDiff(compareTemplate.steps, currentTemplate.steps)
        : [],
    [compareTemplate, currentTemplate],
  );

  const runningCount = useMemo(
    () => runs.filter((run) => run.status === "running").length,
    [runs],
  );

  const visibleRuns = useMemo(() => {
    const base = selectedPipeline
      ? selectedPipeline.source === "project"
        ? runs.filter((run) => run.template_id === selectedPipeline.id)
        : []
      : runs;
    return base.slice(0, 30);
  }, [runs, selectedPipeline]);

  useEffect(() => {
    if (pipelineGroups.length === 0) {
      setSelectedPipelineKey("");
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    if (!pipelineGroups.some((item) => item.key === selectedPipelineKey)) {
      setSelectedPipelineKey(pipelineGroups[0].key);
    }
  }, [pipelineGroups, selectedPipelineKey]);

  useEffect(() => {
    if (!selectedPipeline) {
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    const versions = selectedPipeline.versions;
    if (versions.length === 0) {
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    if (!versions.some((item) => normalizeVersion(item.version) === selectedCurrentVersion)) {
      setSelectedCurrentVersion(normalizeVersion(versions[0].version));
    }

    if (
      selectedCompareVersion &&
      !versions.some((item) => normalizeVersion(item.version) === selectedCompareVersion)
    ) {
      setSelectedCompareVersion("");
    }
  }, [selectedCompareVersion, selectedCurrentVersion, selectedPipeline]);

  useEffect(() => {
    if (selectedCompareVersion && selectedCompareVersion === selectedCurrentVersion) {
      setSelectedCompareVersion("");
    }
  }, [selectedCompareVersion, selectedCurrentVersion]);

  const handleOpenDesignChat = async (withEditMode = false, target?: EditChatTarget) => {
    setDesignChatStarting(true);
    try {
      const source = "pipelines_page" as const;
      const targetPipelineName =
        target?.pipelineName || selectedPipeline?.name || selectedPipeline?.id || "unknown";
      const targetVersion = target?.version || currentTemplate?.version || "latest";
      const isEmptyNodes =
        target?.isEmptyNodes ?? ((currentTemplate?.steps?.length || 0) === 0);
      const seedTask = withEditMode
        ? `编辑已有流程: ${targetPipelineName} (${targetVersion})\n请先分析当前节点并给出可执行的改造建议。`
        : undefined;
      const editGuide = t(
        isEmptyNodes
          ? "pipelines.editInputPlaceholderInit"
          : "pipelines.editInputPlaceholder",
        isEmptyNodes
          ? "这是一个新流程，请先定义目标、关键步骤和完成标准，我会帮你生成首版节点草案。"
          : "围绕当前流程 {{name}} ({{version}}) 描述你的改造目标，例如：新增校验节点、调整重试策略、优化输出结构。",
        {
          name: targetPipelineName,
          version: targetVersion,
        },
      );

      const created = await chatApi.createChat({
        name: t("pipelines.designSessionName", "Pipeline Design"),
        session_id: buildPipelineEntrySessionId(),
        user_id: "default",
        channel: "console",
        meta: {},
      });

      setDesignChatSessionId(created.id);
      if (withEditMode) {
        setEditMode(true);
        setEditTargetKey(`${target?.pipelineId || selectedPipeline?.id || "unknown"}@${normalizeVersion(targetVersion)}`);
        setEditWelcomeMode(isEmptyNodes ? "init" : "default");
        setEditGuidePlaceholder(editGuide);
        return;
      }

      const bootstrapPrompt = buildPipelineDesignBootstrapPrompt({
        source,
        agentId: selectedAgent,
        seedTask,
      });

      // Cache the bootstrap prompt so Chat page can show a local user bubble
      // before backend persistence catches up.
      sessionApi.setLastUserMessage(created.id, bootstrapPrompt);
      if (created.session_id) {
        sessionApi.setLastUserMessage(created.session_id, bootstrapPrompt);
      }

      await chatApi.startConsoleChat({
        sessionId: created.session_id || created.id,
        prompt: bootstrapPrompt,
        userId: created.user_id || "default",
        channel: created.channel || "console",
      });

      const to = buildPipelineDesignChatPath(created.id);
      trackNavigation({
        source: "pipelines.handleOpenDesignChat",
        from: "/pipelines",
        to,
        reason: "start-pipeline-design-chat-inline",
      });
    } catch (error) {
      console.error("failed to start pipeline design chat", error);
      message.error(
        t(
          "pipelines.startChatFailed",
          "Failed to start pipeline design chat. Please try again.",
        ),
      );
    } finally {
      setDesignChatStarting(false);
    }
  };

  const handleCreatePipelineAndEnterEdit = async () => {
    if (!selectedAgent) {
      message.warning(t("pipelines.noAgent", "No active agent selected."));
      return;
    }

    const now = Date.now();
    const draftId = `pipeline-${now}`;
    const draftVersion = "0.1.0";
    const draftTemplate: TemplateItem = {
      id: draftId,
      name: t("pipelines.newPipelineName", "新流程"),
      version: draftVersion,
      description: t("pipelines.newPipelineDescription", "待补充流程说明"),
      steps: [],
      projectId: INDEPENDENT_PIPELINE_SCOPE_ID,
      projectName: t("pipelines.independentScope", "独立流程"),
    };

    const draftGroupKey = buildPipelineGroupKey(draftTemplate.id, "independent");
    setTemplates((prev) => [draftTemplate, ...prev]);
    setDraftPipelineKeys((prev) => Array.from(new Set([draftGroupKey, ...prev])));
    setSourceFilter("independent");
    setSelectedPipelineKey(draftGroupKey);
    setSelectedCurrentVersion(normalizeVersion(draftTemplate.version));
    setSelectedCompareVersion("");

    await handleOpenDesignChat(true, {
      pipelineId: draftTemplate.id,
      pipelineName: draftTemplate.name,
      version: draftTemplate.version,
      isEmptyNodes: true,
    });
  };

  const handleSaveDraftPipeline = async () => {
    if (!selectedAgent || !selectedTemplateItem) {
      return;
    }

    const templateId = (selectedTemplateItem.id || "").trim();
    const safeTemplateId = templateId
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "") || `pipeline-${Date.now()}`;

    const templateDoc = {
      id: safeTemplateId,
      name: selectedTemplateItem.name || safeTemplateId,
      version: selectedTemplateItem.version || "0.1.0",
      description: selectedTemplateItem.description || "",
      steps: selectedTemplateItem.steps || [],
    };

    setDraftSaving(true);
    try {
      const savedDraftId = selectedTemplateItem.id;
      const savedDraftKey = buildPipelineGroupKey(savedDraftId, "independent");
      const preservedDraftTemplates = templates.filter(
        (item) => {
          const key = buildPipelineGroupKey(item.id, getTemplateSourceKind(item));
          return draftPipelineKeys.includes(key) && key !== savedDraftKey;
        },
      );
      const preservedDraftKeys = draftPipelineKeys.filter((key) => key !== savedDraftKey);

      await agentsApi.saveAgentPipelineTemplate(selectedAgent, safeTemplateId, {
        id: safeTemplateId,
        name: templateDoc.name,
        version: templateDoc.version,
        description: templateDoc.description,
        steps: templateDoc.steps,
      });

      const data = await loadPipelineManagementData(
        selectedAgent,
        projects,
        independentScopeLabel,
      );

      setTemplates([...preservedDraftTemplates, ...data.templates]);
      setRuns(data.runs);
      setDraftPipelineKeys(preservedDraftKeys);
      setSourceFilter("independent");
      setSelectedPipelineKey(buildPipelineGroupKey(safeTemplateId, "independent"));
      setSelectedCurrentVersion(normalizeVersion(templateDoc.version));
      setSelectedCompareVersion("");

      message.success(t("pipelines.saveDraftSuccess", "流程已保存"));
    } catch (error) {
      console.error("failed to save draft pipeline", error);
      message.error(t("pipelines.saveDraftFailed", "保存流程失败，请重试。"));
    } finally {
      setDraftSaving(false);
    }
  };

  const handleEnterEditMode = async () => {
    if (!selectedPipeline || !currentTemplate) {
      message.warning(t("pipelines.selectPipelineFirst", "Please select a pipeline first."));
      return;
    }

    const targetKey = `${selectedPipeline.id}@${normalizeVersion(currentTemplate.version)}`;
    const isEmptyNodes = (currentTemplate.steps?.length || 0) === 0;
    setEditWelcomeMode(isEmptyNodes ? "init" : "default");
    setEditGuidePlaceholder(
      t(
        isEmptyNodes
          ? "pipelines.editInputPlaceholderInit"
          : "pipelines.editInputPlaceholder",
        isEmptyNodes
          ? "这是一个新流程，请先定义目标、关键步骤和完成标准，我会帮你生成首版节点草案。"
          : "围绕当前流程 {{name}} ({{version}}) 描述你的改造目标，例如：新增校验节点、调整重试策略、优化输出结构。",
        {
          name: selectedPipeline.name || selectedPipeline.id || "unknown",
          version: currentTemplate.version || "latest",
        },
      ),
    );

    if (designChatSessionId && editTargetKey === targetKey) {
      setEditMode(true);
      return;
    }

    await handleOpenDesignChat(true, {
      pipelineId: selectedPipeline.id,
      pipelineName: selectedPipeline.name || selectedPipeline.id,
      version: currentTemplate.version || "latest",
      isEmptyNodes,
    });
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <Title level={3} className={styles.title}>
            {t("pipelines.title", "Pipelines")}
          </Title>
          <Text className={styles.subtitle}>
            {t(
              "pipelines.description",
              "Manage reusable pipeline definitions across projects, then validate and tune in Projects.",
            )}
          </Text>
        </div>
        <div className={styles.actions}>
          <Select
            size="small"
            value={sourceFilter}
            style={{ width: 180 }}
            onChange={(value) => setSourceFilter(value)}
            options={[
              { value: "all", label: t("pipelines.sourceFilterAll", "全部来源") },
              { value: "independent", label: t("pipelines.sourceFilterIndependent", "仅独立模板") },
              { value: "project", label: t("pipelines.sourceFilterProject", "仅项目模板") },
            ]}
          />
          <Button
            data-testid="pipeline-open-design-chat"
            loading={designChatStarting}
            disabled={designChatStarting}
            onClick={() => void handleCreatePipelineAndEnterEdit()}
          >
            {t("pipelines.create", "新建")}
          </Button>
          <Button type="primary" onClick={() => navigate("/projects")}>
            {t("pipelines.openProjects", "Open Projects to Run")}
          </Button>
        </div>
      </div>

      {projects.length === 0 ? (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Text type="secondary">
            {t(
              "pipelines.noProjectsIndependentHint",
              "当前没有项目，但你仍可新建与编辑独立流程草稿。需要落盘时请先创建项目。",
            )}
          </Text>
        </Card>
      ) : null}

      <div className={styles.metrics}>
        <Card size="small" className={styles.metricCard}>
          <Text className={styles.metricLabel}>
            {t("pipelines.totalTemplates", "Template Variants")}
          </Text>
          <div className={styles.metricValue}>{templates.length}</div>
        </Card>
        <Card size="small" className={styles.metricCard}>
          <Text className={styles.metricLabel}>
            {t("pipelines.totalRuns", "Total Runs")}
          </Text>
          <div className={styles.metricValue}>{runs.length}</div>
        </Card>
        <Card size="small" className={styles.metricCard}>
          <Text className={styles.metricLabel}>
            {t("pipelines.runningRuns", "Running")}
          </Text>
          <div className={styles.metricValue}>{runningCount}</div>
        </Card>
      </div>

      <div className={styles.content}>
        {loading ? (
          <div className={styles.loadingWrap}>
            <Spin size="large" />
          </div>
        ) : error ? (
          <Card>
            <Text type="danger">{error}</Text>
          </Card>
        ) : !currentAgent ? (
          <Card>
            <Empty
              description={t("pipelines.noAgent", "No active agent selected.")}
            />
          </Card>
        ) : projects.length === 0 && templates.length === 0 ? (
          <Card>
            <Empty
              description={t(
                "pipelines.noProjects",
                "No projects found for the current agent.",
              )}
            />
          </Card>
        ) : (
          <div className={styles.columns}>
            <Card
              title={t("pipelines.library", "Pipeline Library")}
              className={styles.columnCard}
            >
              {pipelineGroups.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.emptyTemplates",
                    "No pipeline templates found yet.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {pipelineGroups.map((item) => {
                    const selected = item.key === selectedPipelineKey;
                    return (
                      <button
                        key={item.key}
                        type="button"
                        className={`${styles.listItem} ${selected ? styles.selected : ""}`}
                        onClick={() => requestSelectPipeline(item.key)}
                      >
                        <div className={styles.listItemHeader}>
                          <Text strong>{item.name}</Text>
                          <Tag>{item.versions.length}</Tag>
                          <Tag color={item.source === "independent" ? "cyan" : "gold"}>
                            {item.source === "independent"
                              ? t("pipelines.sourceIndependent", "独立")
                              : t("pipelines.sourceProject", "项目")}
                          </Tag>
                          {draftPipelineKeys.includes(item.key) ? (
                            <Tag color="warning">
                              {t("pipelines.draftBadge", "未保存")}
                            </Tag>
                          ) : null}
                        </div>
                        <Text type="secondary">{item.description || item.id}</Text>
                        <Text type="secondary" className={styles.helperText}>
                          {t("pipelines.versionCount", "Versions: {{count}}", {
                            count: item.versions.length,
                          })}
                        </Text>
                        <Text type="secondary" className={styles.helperText}>
                          {t("pipelines.usedIn", "Used in {{count}} projects", {
                            count: item.projects.length,
                          })}
                        </Text>
                      </button>
                    );
                  })}
                </div>
              )}
            </Card>

            <Card
              title={t("pipelines.nodes", "Current Nodes")}
              className={styles.columnCard}
              extra={
                <div className={styles.nodesActions}>
                  <Select
                    size="small"
                    className={styles.versionSelect}
                    value={selectedCurrentVersion || undefined}
                    placeholder={t("pipelines.currentVersion", "Current version")}
                    options={(selectedPipeline?.versions || []).map((item) => ({
                      label: item.version || "0",
                      value: normalizeVersion(item.version),
                    }))}
                    onChange={(value) => {
                      setSelectedCurrentVersion(value);
                      if (value === selectedCompareVersion) {
                        setSelectedCompareVersion("");
                      }
                    }}
                  />
                  {editMode ? (
                    <>
                      {selectedIsDraft ? (
                        <Button
                          size="small"
                          type="primary"
                          loading={draftSaving}
                          disabled={draftSaving}
                          onClick={() => void handleSaveDraftPipeline()}
                        >
                          {t("pipelines.saveDraft", "保存")}
                        </Button>
                      ) : null}
                      <Button
                        size="small"
                        onClick={requestCloseEditMode}
                      >
                        {t("pipelines.exitEdit", "Exit Edit")}
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="small"
                      type="primary"
                      loading={designChatStarting}
                      disabled={!currentTemplate || designChatStarting}
                      onClick={() => void handleEnterEditMode()}
                    >
                      {t("pipelines.enterEdit", "Edit Pipeline")}
                    </Button>
                  )}
                </div>
              }
            >
              {!currentTemplate ? (
                <Empty
                  description={t(
                    "pipelines.selectPipeline",
                    "Select a pipeline to view nodes.",
                  )}
                />
              ) : currentTemplate.steps.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.emptyNodes",
                    "No nodes in this pipeline version.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {currentTemplate.steps.map((step) => (
                    <div key={step.id} className={styles.listItemStatic}>
                      <div className={styles.listItemHeader}>
                        <Text strong>{step.name}</Text>
                        <Tag color="blue">{step.kind}</Tag>
                      </div>
                      <Text type="secondary">{step.id}</Text>
                      <Text type="secondary" className={styles.helperText}>
                        {step.description || "-"}
                      </Text>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card
              title={t("pipelines.newVersionNodes", "New Version Nodes")}
              className={styles.columnCard}
              extra={
                <Select
                  size="small"
                  className={styles.versionSelect}
                  value={selectedCompareVersion || undefined}
                  allowClear
                  placeholder={t("pipelines.compareVersion", "Select history version")}
                  options={(selectedPipeline?.versions || [])
                    .filter((item) => normalizeVersion(item.version) !== selectedCurrentVersion)
                    .map((item) => ({
                      label: item.version || "0",
                      value: normalizeVersion(item.version),
                    }))}
                  onChange={(value) => setSelectedCompareVersion(value || "")}
                />
              }
            >
              {!compareTemplate ? (
                <Empty
                  description={t(
                    "pipelines.selectNewVersion",
                    "Select a version as the new draft to compare with current nodes.",
                  )}
                />
              ) : newVersionDiffItems.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.noDiff",
                    "No diff available for this version pair.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {newVersionDiffItems.map((item) => (
                    <div key={`${item.kind}-${item.id}`} className={styles.listItemStatic}>
                      <div className={styles.listItemHeader}>
                        <Text strong>{item.current?.name || item.compare?.name || item.id}</Text>
                        <Tag
                          color={
                            item.kind === "added"
                              ? "success"
                              : item.kind === "removed"
                                ? "error"
                                : item.kind === "changed"
                                  ? "warning"
                                  : "default"
                          }
                        >
                          {item.kind === "added"
                            ? t("pipelines.diffAdded", "Added")
                            : item.kind === "removed"
                              ? t("pipelines.diffRemoved", "Removed")
                              : item.kind === "changed"
                                ? t("pipelines.diffChanged", "Changed")
                                : t("pipelines.diffUnchanged", "Unchanged")}
                        </Tag>
                      </div>
                      <Text type="secondary">{item.id}</Text>
                      <Text type="secondary" className={styles.helperText}>
                        {item.current?.description || item.compare?.description || "-"}
                      </Text>
                      {item.kind === "changed" && item.changedFields.length > 0 && (
                        <Text type="secondary" className={styles.helperText}>
                          {t("pipelines.diffFields", "Changed: {{fields}}", {
                            fields: item.changedFields.join(", "),
                          })}
                        </Text>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card
              title={editMode ? t("pipelines.editChat", "Pipeline Edit Chat") : t("pipelines.recentRuns", "Recent Runs")}
              className={`${styles.columnCard} ${editMode ? styles.chatColumn : ""}`}
              extra={
                editMode && designChatSessionId ? (
                  <Button size="small" onClick={() => navigate(`/chat/${designChatSessionId}`)}>
                    {t("pipelines.openInFullChat", "Open Full Chat")}
                  </Button>
                ) : undefined
              }
              styles={editMode ? { body: { padding: 0, height: "calc(100% - 56px)", overflow: "hidden" } } : undefined}
            >
              {editMode ? (
                designChatStarting ? (
                  <div className={styles.chatLoadingWrap}>
                    <Spin size="large" />
                  </div>
                ) : designChatSessionId ? (
                  <AnywhereChat
                    sessionId={designChatSessionId}
                    inputPlaceholder={editGuidePlaceholder || undefined}
                    welcomeGreeting={t(
                      editWelcomeMode === "init"
                        ? "pipelines.editWelcomeGreetingInit"
                        : "pipelines.editWelcomeGreeting",
                      editWelcomeMode === "init"
                        ? "新流程已创建，我们先把首版流程搭起来。"
                        : "流程编辑助手已就绪，你想先改哪一步？",
                    )}
                    welcomeDescription={t(
                      editWelcomeMode === "init"
                        ? "pipelines.editWelcomeDescriptionInit"
                        : "pipelines.editWelcomeDescription",
                      editWelcomeMode === "init"
                        ? "你可以先描述目标、输入和产出，我会生成初始化节点并给出参数建议。"
                        : "我会基于当前流程结构给出节点级修改建议，并帮助你整理可执行的改造方案。",
                    )}
                    welcomePrompts={[
                      t(
                        editWelcomeMode === "init"
                          ? "pipelines.editWelcomePromptInit1"
                          : "pipelines.editWelcomePrompt1",
                        editWelcomeMode === "init"
                          ? "为这个新流程生成首版节点（目标、输入、步骤、验收标准）。"
                          : "分析当前流程瓶颈，并给出 3 条可执行优化建议（含节点改动）。",
                      ),
                      t(
                        editWelcomeMode === "init"
                          ? "pipelines.editWelcomePromptInit2"
                          : "pipelines.editWelcomePrompt2",
                        editWelcomeMode === "init"
                          ? "先给我 5 个澄清问题，再输出可直接执行的流程草案。"
                          : "我要改这个流程：新增校验节点、调整重试策略，并输出变更后的步骤清单。",
                      ),
                    ]}
                  />
                ) : (
                  <Empty
                    description={t(
                      "pipelines.chatPanelHint",
                      "Start a design chat to iterate without leaving this page.",
                    )}
                  />
                )
              ) : visibleRuns.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.emptyRuns",
                    "No pipeline runs yet.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {visibleRuns.map((run) => (
                    <div key={run.id} className={styles.listItemStatic}>
                      <div className={styles.listItemHeader}>
                        <Text strong>{run.template_id}</Text>
                        <Tag color={statusTagColor(run.status)}>{run.status}</Tag>
                      </div>
                      <Text type="secondary">
                        {t("pipelines.projectLabel", "Project: {{name}}", {
                          name: run.projectName,
                        })}
                      </Text>
                      <Text type="secondary" className={styles.helperText}>
                        {run.updated_at || run.created_at}
                      </Text>
                      <div className={styles.runActions}>
                        <Button
                          size="small"
                          type="link"
                          className={styles.runLink}
                          onClick={() => {
                            setSourceFilter("project");
                            setSelectedPipelineKey(
                              buildPipelineGroupKey(run.template_id, "project"),
                            );
                            setSelectedCompareVersion("");
                          }}
                        >
                          {t("pipelines.focusPipeline", "Focus Pipeline")}
                        </Button>
                        <Button
                          size="small"
                          type="link"
                          className={styles.runLink}
                          onClick={() => navigate("/projects")}
                        >
                          {t("pipelines.goToProjects", "Go to Projects")}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}