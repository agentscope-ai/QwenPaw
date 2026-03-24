import { useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Spin, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "../../../api/modules/agents";
import { chatApi } from "../../../api/modules/chat";
import {
  buildPipelineDesignBootstrapPrompt,
  buildPipelineDesignChatPath,
  queuePipelineDesignBootstrap,
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

export default function PipelinesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { selectedAgent, agents, setAgents } = useAgentStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [runs, setRuns] = useState<RunItem[]>([]);

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

  const uniqueTemplates = useMemo(() => {
    const map = new Map<string, TemplateItem[]>();
    templates.forEach((item) => {
      const key = `${item.id}@${item.version}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)?.push(item);
    });
    return Array.from(map.entries()).map(([key, items]) => ({
      key,
      id: items[0].id,
      version: items[0].version,
      name: items[0].name,
      description: items[0].description,
      projects: items.map((it) => ({ id: it.projectId, name: it.projectName })),
    }));
  }, [templates]);

  const runningCount = useMemo(
    () => runs.filter((run) => run.status === "running").length,
    [runs],
  );

  const handleOpenDesignChat = async () => {
    const source = "pipelines_page" as const;
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
    });
    queuePipelineDesignBootstrap(created.id, bootstrapPrompt);
    const to = buildPipelineDesignChatPath(created.id, source);
    trackNavigation({
      source: "pipelines.handleOpenDesignChat",
      from: "/pipelines",
      to,
      reason: "start-pipeline-design-chat",
    });
    navigate(to);
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
            onClick={() => void handleOpenDesignChat()}
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
          <div className={styles.metricValue}>{uniqueTemplates.length}</div>
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
            {uniqueTemplates.length === 0 ? (
              <Empty
                description={t(
                  "pipelines.emptyTemplates",
                  "No pipeline templates found yet.",
                )}
              />
            ) : (
              <div className={styles.list}>
                {uniqueTemplates.map((item) => (
                  <div key={item.key} className={styles.listItem}>
                    <div className={styles.listItemHeader}>
                      <Text strong>{item.name}</Text>
                      <Tag>{item.version}</Tag>
                    </div>
                    <Text type="secondary">{item.description || item.id}</Text>
                    <Text type="secondary" className={styles.helperText}>
                      {t("pipelines.usedIn", "Used in {{count}} projects", {
                        count: item.projects.length,
                      })}
                    </Text>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card
            title={t("pipelines.recentRuns", "Recent Runs")}
            className={styles.columnCard}
          >
            {runs.length === 0 ? (
              <Empty
                description={t(
                  "pipelines.emptyRuns",
                  "No pipeline runs yet.",
                )}
              />
            ) : (
              <div className={styles.list}>
                {runs.slice(0, 20).map((run) => (
                  <div key={run.id} className={styles.listItem}>
                    <div className={styles.listItemHeader}>
                      <Text strong>{run.template_id}</Text>
                      <Tag color={statusTagColor(run.status)}>{run.status}</Tag>
                    </div>
                    <Text type="secondary">
                      {t("pipelines.projectLabel", "Project: {{name}}", {
                        name: run.projectName,
                      })}
                    </Text>
                    <Button
                      size="small"
                      type="link"
                      className={styles.runLink}
                      onClick={() => navigate("/projects")}
                    >
                      {t("pipelines.goToProjects", "Go to Projects")}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}