import { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Select, Spin, Tag, Typography, message } from "antd";
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

type PipelineGroup = {
  id: string;
  name: string;
  description: string;
  versions: ProjectPipelineTemplateInfo[];
  projects: { id: string; name: string }[];
};

type StepDiffItem = {
  id: string;
  kind: "added" | "removed" | "changed" | "unchanged";
  current?: { name: string; kind: string; description: string };
  compare?: { name: string; kind: string; description: string };
  changedFields: string[];
};

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
  const [selectedPipelineId, setSelectedPipelineId] = useState("");
  const [selectedCurrentVersion, setSelectedCurrentVersion] = useState("");
  const [selectedCompareVersion, setSelectedCompareVersion] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [designChatStarting, setDesignChatStarting] = useState(false);
  const [designChatSessionId, setDesignChatSessionId] = useState("");
  const [editTargetKey, setEditTargetKey] = useState("");

  const currentAgent = useMemo(
    () => getCurrentAgent(agents, selectedAgent),
    [agents, selectedAgent],
  );

  const projects = useMemo<AgentProjectSummary[]>(
    () => currentAgent?.projects ?? [],
    [currentAgent?.projects],
  );

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
        if (projectList.length === 0) {
          if (!mounted) return;
          setTemplates([]);
          setRuns([]);
          return;
        }

        const perProject = await Promise.all(
          projectList.map(async (project) => {
            const [templatesResult, runsResult] = await Promise.allSettled([
              agentsApi.listProjectPipelineTemplates(selectedAgent, project.id),
              agentsApi.listProjectPipelineRuns(selectedAgent, project.id),
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
        );

        if (!mounted) return;

        const mergedTemplates: TemplateItem[] = perProject.flatMap((item) =>
          item.templates.map((tpl) => ({
            ...tpl,
            projectId: item.project.id,
            projectName: item.project.name,
          })),
        );

        const mergedRuns: RunItem[] = perProject
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

        setTemplates(mergedTemplates);
        setRuns(mergedRuns);
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
  }, [agents, selectedAgent, setAgents, t]);

  const pipelineGroups = useMemo<PipelineGroup[]>(() => {
    const map = new Map<string, TemplateItem[]>();
    templates.forEach((item) => {
      if (!map.has(item.id)) {
        map.set(item.id, []);
      }
      map.get(item.id)?.push(item);
    });

    return Array.from(map.entries())
      .map(([id, items]) => {
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

        return {
          id,
          name: items[0].name,
          description: items[0].description,
          versions,
          projects: Array.from(projectMap.values()),
        };
      })
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }, [templates]);

  const selectedPipeline = useMemo(
    () => pipelineGroups.find((item) => item.id === selectedPipelineId),
    [pipelineGroups, selectedPipelineId],
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
    const base = selectedPipelineId
      ? runs.filter((run) => run.template_id === selectedPipelineId)
      : runs;
    return base.slice(0, 30);
  }, [runs, selectedPipelineId]);

  useEffect(() => {
    if (pipelineGroups.length === 0) {
      setSelectedPipelineId("");
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    if (!pipelineGroups.some((item) => item.id === selectedPipelineId)) {
      setSelectedPipelineId(pipelineGroups[0].id);
    }
  }, [pipelineGroups, selectedPipelineId]);

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

  const handleOpenDesignChat = async (withEditMode = false) => {
    setDesignChatStarting(true);
    try {
      const source = "pipelines_page" as const;
      const targetPipelineName = selectedPipeline?.name || selectedPipeline?.id || "unknown";
      const targetVersion = currentTemplate?.version || "latest";
      const seedTask = withEditMode
        ? `编辑已有流程: ${targetPipelineName} (${targetVersion})\n请先分析当前节点并给出可执行的改造建议。`
        : undefined;

      const created = await chatApi.createChat({
        name: t("pipelines.designSessionName", "Pipeline Design"),
        session_id: buildPipelineEntrySessionId(),
        user_id: "default",
        channel: "console",
        meta: {},
      });

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

      setDesignChatSessionId(created.id);
      if (withEditMode) {
        setEditMode(true);
        setEditTargetKey(
          `${selectedPipeline?.id || "unknown"}@${normalizeVersion(currentTemplate?.version || "")}`,
        );
      }
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

  const handleEnterEditMode = async () => {
    if (!selectedPipeline || !currentTemplate) {
      message.warning(t("pipelines.selectPipelineFirst", "Please select a pipeline first."));
      return;
    }

    const targetKey = `${selectedPipeline.id}@${normalizeVersion(currentTemplate.version)}`;
    if (designChatSessionId && editTargetKey === targetKey) {
      setEditMode(true);
      return;
    }

    await handleOpenDesignChat(true);
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
          <Button
            data-testid="pipeline-open-design-chat"
            loading={designChatStarting}
            disabled={designChatStarting}
            onClick={() => void handleOpenDesignChat(false)}
          >
            {t("pipelines.openChat", "Open Chat to Design")}
          </Button>
          <Button type="primary" onClick={() => navigate("/projects")}>
            {t("pipelines.openProjects", "Open Projects to Run")}
          </Button>
        </div>
      </div>

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
        ) : projects.length === 0 ? (
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
                    const selected = item.id === selectedPipelineId;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        className={`${styles.listItem} ${selected ? styles.selected : ""}`}
                        onClick={() => {
                          setSelectedPipelineId(item.id);
                          setSelectedCompareVersion("");
                        }}
                      >
                        <div className={styles.listItemHeader}>
                          <Text strong>{item.name}</Text>
                          <Tag>{item.versions.length}</Tag>
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
                    <Button size="small" onClick={() => setEditMode(false)}>
                      {t("pipelines.exitEdit", "Exit Edit")}
                    </Button>
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
                  <AnywhereChat sessionId={designChatSessionId} />
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
                            setSelectedPipelineId(run.template_id);
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