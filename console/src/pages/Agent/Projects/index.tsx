import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Select,
  Spin,
  Tag,
  Tabs,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../../api/modules/agents";
import type {
  AgentProjectFileInfo,
  ProjectPipelineRunDetail,
  ProjectPipelineRunSummary,
  ProjectPipelineTemplateInfo,
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

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
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

export default function ProjectsPage() {
  const { t } = useTranslation();
  const { selectedAgent, agents, setAgents } = useAgentStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [selectedProjectId, setSelectedProjectId] = useState("");
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

  const currentAgent = useMemo(
    () => getCurrentAgent(agents, selectedAgent),
    [agents, selectedAgent],
  );

  const projects = useMemo(
    () => currentAgent?.projects ?? [],
    [currentAgent?.projects],
  );
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId),
    [projects, selectedProjectId],
  );

  const artifactPaths = useMemo(
    () => runDetail?.artifacts ?? projectFiles.map((file) => file.path),
    [projectFiles, runDetail?.artifacts],
  );

  const selectedRunSummary = useMemo(
    () => pipelineRuns.find((run) => run.id === selectedRunId),
    [pipelineRuns, selectedRunId],
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

  const loadProjectFiles = useCallback(async (agentId: string, projectId: string) => {
    setFilesLoading(true);
    setSelectedFilePath("");
    setFileContent("");
    try {
      const files = await agentsApi.listProjectFiles(agentId, projectId);
      setProjectFiles(files);
      if (files.length > 0) {
        setSelectedFilePath(files[0].path);
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
    projectId: string,
    filePath: string,
  ) => {
    setContentLoading(true);
    setFileContent("");
    try {
      const data = await agentsApi.readProjectFile(agentId, projectId, filePath);
      setFileContent(data.content);
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
  }, [t]);

  const loadRunDetail = useCallback(async (
    agentId: string,
    projectId: string,
    runId: string,
  ) => {
    try {
      const detail = await agentsApi.getProjectPipelineRun(agentId, projectId, runId);
      setRunDetail(detail);
      if (detail.artifacts.length > 0 && !selectedFilePath) {
        setSelectedFilePath(detail.artifacts[0]);
      }
    } catch (err) {
      console.error("failed to load pipeline run detail", err);
      setRunDetail(null);
      setError(
        t("projects.pipeline.loadRunFailed", "Failed to load pipeline run detail."),
      );
    }
  }, [selectedFilePath, t]);

  const loadPipelineContext = useCallback(async (
    agentId: string,
    projectId: string,
  ) => {
    setPipelineLoading(true);
    try {
      const [templates, runs] = await Promise.all([
        agentsApi.listProjectPipelineTemplates(agentId, projectId),
        agentsApi.listProjectPipelineRuns(agentId, projectId),
      ]);
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
        setSelectedRunId((prev) => (runs.some((item) => item.id === prev) ? prev : runs[0].id));
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
        t("projects.pipeline.loadFailed", "Failed to load pipeline templates and runs."),
      );
    } finally {
      setPipelineLoading(false);
    }
  }, [t]);

  const pollPipelineRun = useCallback(async (
    agentId: string,
    projectId: string,
    runId: string,
  ) => {
    try {
      const [runs, detail] = await Promise.all([
        agentsApi.listProjectPipelineRuns(agentId, projectId),
        agentsApi.getProjectPipelineRun(agentId, projectId, runId),
      ]);
      setPipelineRuns(runs);
      setRunDetail(detail);
    } catch (err) {
      console.error("failed to poll pipeline run", err);
    }
  }, []);

  const handleCreateRun = useCallback(async () => {
    if (!currentAgent || !selectedProject || !selectedTemplateId) {
      return;
    }
    setCreateRunLoading(true);
    try {
      const run = await agentsApi.createProjectPipelineRun(
        currentAgent.id,
        selectedProject.id,
        { template_id: selectedTemplateId },
      );
      await loadPipelineContext(currentAgent.id, selectedProject.id);
      setSelectedRunId(run.id);
      setRunDetail(run);
    } catch (err) {
      console.error("failed to create pipeline run", err);
      setError(
        t("projects.pipeline.createRunFailed", "Failed to start pipeline run."),
      );
    } finally {
      setCreateRunLoading(false);
    }
  }, [currentAgent, loadPipelineContext, selectedProject, selectedTemplateId, t]);

  useEffect(() => {
    if (!currentAgent) {
      void loadAgents();
    }
  }, [currentAgent, loadAgents]);

  useEffect(() => {
    if (!currentAgent || projects.length === 0) {
      setSelectedProjectId("");
      setProjectFiles([]);
      setSelectedFilePath("");
      setFileContent("");
      return;
    }

    if (!projects.some((project) => project.id === selectedProjectId)) {
      setSelectedProjectId(projects[0].id);
    }
  }, [currentAgent, projects, selectedProjectId]);

  useEffect(() => {
    if (!currentAgent || !selectedProjectId) {
      return;
    }
    void loadProjectFiles(currentAgent.id, selectedProjectId);
    void loadPipelineContext(currentAgent.id, selectedProjectId);
  }, [currentAgent, selectedProjectId, loadProjectFiles, loadPipelineContext]);

  useEffect(() => {
    if (!currentAgent || !selectedProject || !selectedFilePath) {
      return;
    }
    void loadFileContent(currentAgent.id, selectedProject.id, selectedFilePath);
  }, [currentAgent, selectedProject, selectedFilePath, loadFileContent]);

  useEffect(() => {
    if (!currentAgent || !selectedProject || !selectedRunId) {
      return;
    }
    void loadRunDetail(currentAgent.id, selectedProject.id, selectedRunId);
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
      void pollPipelineRun(currentAgent.id, selectedProject.id, selectedRunId);
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

  return (
    <div className={styles.agentsPage}>
      <div className={styles.header}>
        <div>
          <Title level={4} className={styles.title}>
            {t("projects.title", "Projects")}
          </Title>
          <Text type="secondary" className={styles.description}>
            {t(
              "projects.description",
              "Browse the projects stored under the current agent workspace.",
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
      ) : (
        <div className={styles.content}>
          <div className={styles.columnLeft}>
            <Card
              title={
                <span className={styles.sectionTitle}>{t("projects.list", "Projects")}</span>
              }
              styles={{ body: { padding: 12 } }}
            >
              <div className={styles.scrollContainer}>
                {projects.map((project) => {
                  const selected = project.id === selectedProjectId;
                  return (
                    <button
                      key={project.id}
                      type="button"
                      className={`${styles.listItem} ${selected ? styles.selected : ""}`}
                      onClick={() => setSelectedProjectId(project.id)}
                    >
                      <div className={styles.itemTitleRow}>
                        <span className={styles.itemTitle}>{project.name}</span>
                        <Tag color="blue">{project.status}</Tag>
                      </div>
                      <div className={styles.itemMeta}>{project.id}</div>
                      <div className={styles.itemMeta}>{project.updated_time}</div>
                    </button>
                  );
                })}
              </div>
            </Card>
          </div>

          <div className={styles.columnMiddle}>
            <Card
              title={
                <span className={styles.sectionTitle}>{t("projects.pipeline.title", "Pipeline")}</span>
              }
              styles={{ body: { padding: 12 } }}
              extra={
                <Text type="secondary" className={styles.panelExtraText}>
                  {selectedRunSummary?.status || t("projects.pipeline.noRun", "No run")}
                </Text>
              }
            >
              <div className={styles.scrollContainer}>
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
                ) : pipelineRuns.length === 0 ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("projects.pipeline.noRuns", "No pipeline runs yet")}
                  />
                ) : (
                  <>
                    <div className={styles.runList}>
                      {pipelineRuns.map((run) => {
                        const selected = run.id === selectedRunId;
                        return (
                          <button
                            key={run.id}
                            type="button"
                            className={`${styles.listItem} ${selected ? styles.selected : ""}`}
                            onClick={() => setSelectedRunId(run.id)}
                          >
                            <div className={styles.itemTitleRow}>
                              <span className={styles.itemTitle}>{run.id}</span>
                              <Tag color={statusTagColor(run.status)}>{run.status}</Tag>
                            </div>
                            <div className={styles.itemMeta}>{run.template_id}</div>
                            <div className={styles.itemMeta}>{run.updated_at}</div>
                          </button>
                        );
                      })}
                    </div>

                    <div className={styles.stepPanel}>
                      <div className={styles.subSectionTitle}>
                        {t("projects.pipeline.steps", "Steps")}
                      </div>
                      {runDetail && (
                        <div className={styles.progressLine}>
                          {t("projects.pipeline.progress", "Progress")}: {runProgress.completed}/
                          {runProgress.total} · running {runProgress.running} · pending {runProgress.pending}
                        </div>
                      )}
                      {!runDetail || runDetail.steps.length === 0 ? (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("projects.pipeline.noSteps", "No steps available")}
                        />
                      ) : (
                        runDetail.steps.map((step) => (
                          <div key={step.id} className={styles.stepItem}>
                            <div className={styles.itemTitleRow}>
                              <span className={styles.itemTitle}>{step.name}</span>
                              <Tag color={statusTagColor(step.status)}>{step.status}</Tag>
                            </div>
                            <div className={styles.itemMeta}>{step.kind}</div>
                            <div className={styles.itemMeta}>{step.id}</div>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                )}
              </div>
            </Card>
          </div>

          <div className={styles.columnRight}>
            <Card
              title={
                <span className={styles.sectionTitle}>{t("projects.preview", "Workbench")}</span>
              }
              styles={{ body: { padding: 0 } }}
              extra={
                <Text type="secondary" className={styles.panelExtraText}>
                  {selectedProject?.id || ""}
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
                        ) : artifactPaths.length === 0 ? (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("projects.noFiles", "No files in this project")}
                          />
                        ) : (
                          <div className={styles.artifactPanel}>
                            <div className={styles.artifactList}>
                              {artifactPaths.map((path) => {
                                const selected = path === selectedFilePath;
                                const fileInfo = projectFiles.find((file) => file.path === path);
                                return (
                                  <button
                                    key={path}
                                    type="button"
                                    className={`${styles.listItem} ${selected ? styles.selected : ""}`}
                                    onClick={() => setSelectedFilePath(path)}
                                  >
                                    <div className={styles.itemTitle}>{fileInfo?.filename || path}</div>
                                    <div className={styles.itemMeta}>{path}</div>
                                    {fileInfo && (
                                      <div className={styles.itemMeta}>
                                        {formatBytes(fileInfo.size)} · {fileInfo.modified_time}
                                      </div>
                                    )}
                                  </button>
                                );
                              })}
                            </div>
                            <div className={styles.previewPane}>
                              {contentLoading ? (
                                <div className={styles.centerState}>
                                  <Spin />
                                </div>
                              ) : selectedFilePath ? (
                                <pre className={styles.previewContent}>{fileContent}</pre>
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
        </div>
      )}
    </div>
  );
}