import { useEffect, useState, useCallback, memo } from "react";
import { Modal, message } from "antd";
import {
  Plus,
  Trash2,
  ExternalLink,
  Film,
  Clock3,
  ArrowUp,
  ArrowDown,
  CircleHelp,
} from "lucide-react";
import type { ModelConfigData, ProjectSummary } from "@/contracts/creator";
import { deleteProject, getModelConfig, listProjects } from "@/api/creator";
import { useRouter } from "@/routing/navigation";
import ModelBadges from "@/components/creator/ModelBadges";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import {
  ProjectComposer,
  SCENARIO_OPTIONS,
  CONTENT_TYPE_OPTIONS,
} from "@/components/creator/ProjectComposer";
import { HomeTour } from "@/components/onboarding";
import { useOnboardingStore } from "@/store/onboardingStore";

interface ProjectCardProps {
  project: ProjectSummary;
  onOpen: (id: string) => void;
  onDelete: (project: ProjectSummary) => void;
  formatDate: (dateStr: string) => string;
}

const ProjectCard = memo(function ProjectCard({
  project,
  onOpen,
  onDelete,
  formatDate,
}: ProjectCardProps) {
  var projectScenarioLabel = "未设置";
  if (project.scenario !== undefined) {
    projectScenarioLabel =
      SCENARIO_OPTIONS.find((option) => option.key === project.scenario)
        ?.label ?? project.scenario;
  }
  var projectContentType = "未设置";
  if (project.contentType) {
    projectContentType =
      CONTENT_TYPE_OPTIONS.find((option) => option.key === project.contentType)
        ?.label ?? project.contentType;
  }
  return (
    <div className="surface surface-hover flex min-h-[188px] flex-col p-4">
      <h3 className="mb-2 truncate text-[15px] font-semibold leading-6 text-[var(--color-text-primary)]">
        {project.name}
      </h3>
      <div className="mb-3 min-h-[52px] rounded-md border border-[#f3f1f0] bg-[rgba(43,18,0,0.02)] px-3 py-2">
        {project.description ? (
          <p className="line-clamp-2 text-[13px] leading-5 text-[var(--color-text-secondary)]">
            {project.description}
          </p>
        ) : (
          <p className="text-[13px] leading-5 text-[var(--color-text-tertiary)]">
            暂无项目描述
          </p>
        )}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <span className="badge border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]">
          视频场景 {projectScenarioLabel}
        </span>
        <span className="badge border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]">
          内容类型 {projectContentType}
        </span>
        <span className="badge border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]">
          画面长宽比 {project.aspectRatio}
        </span>
        <span className="badge border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]">
          图像分辨率 {project.resolution}
        </span>
      </div>
      <div className="mb-4 flex items-center gap-4 text-xs text-[var(--color-text-tertiary)]">
        <p className="flex items-center gap-1.5">
          <Clock3 className="h-3.5 w-3.5" />
          创建于 {formatDate(project.createdAt)}
        </p>
        <p className="flex items-center gap-1.5">
          <Clock3 className="h-3.5 w-3.5" />
          更新于 {formatDate(project.updatedAt)}
        </p>
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-[var(--color-border)] pt-3">
        <button
          onClick={() => onOpen(project.projectId)}
          className="btn-primary flex-1 cursor-pointer"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          打开
        </button>
        <button
          onClick={() => onDelete(project)}
          className="btn-primary flex-1 cursor-pointer"
          aria-label={`删除 ${project.name}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
          删除
        </button>
      </div>
    </div>
  );
});

type SortField = "updated_at" | "created_at" | "name";

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "updated_at", label: "按更新时间" },
  { value: "created_at", label: "按创建时间" },
  { value: "name", label: "按项目名称" },
];

export default function HomePage() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [composerOpen, setComposerOpen] = useState(false);
  const [sortBy, setSortBy] = useState<SortField>("updated_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const requestHomeTour = useOnboardingStore((state) => state.requestHomeTour);
  const [modelConfig, setModelConfig] = useState<ModelConfigData | null>(null);
  const [configModalOpen, setConfigModalOpen] = useState(false);

  const refreshModelConfig = useCallback(() => {
    getModelConfig()
      .then(setModelConfig)
      .catch(() => setModelConfig(null));
  }, []);

  useEffect(() => {
    refreshModelConfig();
  }, [refreshModelConfig]);

  // An LLM is required for every creation scenario; keep reminding on the home page until configured.
  const llmReady =
    modelConfig === null ||
    Boolean(modelConfig.llm.enabled && modelConfig.llm.model_name);

  const fetchProjects = useCallback(
    async (sort: SortField = sortBy, order: "asc" | "desc" = sortOrder) => {
      try {
        const data = await listProjects(100, 0, sort, order);
        setProjects(data.items || []);
      } catch {
        message.error("加载项目列表失败");
      } finally {
        setLoading(false);
      }
    },
    [sortBy, sortOrder],
  );

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);

  const handleOpen = useCallback(
    (id: string) => {
      router.push(`/project/${id}/plan`);
    },
    [router],
  );

  const handleDelete = useCallback(
    (project: ProjectSummary) => {
      Modal.confirm({
        title: "确认删除",
        content: `确定要删除项目「${project.name}」吗？此操作不可撤销。`,
        okText: "删除",
        cancelText: "取消",
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await deleteProject(project.projectId);
            message.success("项目已删除");
            fetchProjects();
          } catch {
            message.error("删除项目失败");
          }
        },
      });
    },
    [fetchProjects],
  );

  const handleSortChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const value = e.target.value as SortField;
      setSortBy(value);
      fetchProjects(value, sortOrder);
    },
    [fetchProjects, sortOrder],
  );

  const handleSortOrderToggle = useCallback(() => {
    const newOrder = sortOrder === "asc" ? "desc" : "asc";
    setSortOrder(newOrder);
    fetchProjects(sortBy, newOrder);
  }, [fetchProjects, sortBy, sortOrder]);

  const formatDate = useCallback((dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }, []);

  return (
    <div className="min-h-full app-shell">
      <header className="border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]">
        <div className="page-container flex h-16 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-accent)] text-white">
              <Film className="h-4 w-4" />
            </div>
            <div>
              <span className="block text-lg font-semibold text-[var(--color-text-primary)]">
                QwenPaw Creator
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={requestHomeTour}
              className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-[var(--color-text-tertiary)] transition-colors hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
              title="重新查看新手引导"
              aria-label="重新查看新手引导"
            >
              <CircleHelp className="h-4 w-4" />
            </button>
            <ModelBadges />
          </div>
        </div>
      </header>

      <main className="page-container py-4">
        {!llmReady && (
          <button
            type="button"
            onClick={() => setConfigModalOpen(true)}
            className="mb-4 flex w-full flex-wrap items-center gap-2 rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)]/50 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]"
          >
            <span className="text-xs font-semibold text-[var(--color-warning)]">
              还未配置 LLM 模型
            </span>
            <span className="min-w-0 flex-1 text-[11px] text-[var(--color-text-secondary)]">
              LLM 是所有创作场景的必选模型，配置并通过连通性测试后才能启动
              Agent。
            </span>
            <span className="shrink-0 text-[11px] font-semibold text-[var(--color-accent)]">
              立即配置 →
            </span>
          </button>
        )}
        <section className="mb-4 rounded-lg border border-[var(--color-border)] bg-[rgba(255,255,255,0.5)] p-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
                我的项目
              </h1>
              <div className="flex items-center gap-1.5">
                <select
                  value={sortBy}
                  onChange={handleSortChange}
                  className="cursor-pointer rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1 text-sm text-[var(--color-text-secondary)] outline-none focus:border-[var(--color-accent)]"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleSortOrderToggle}
                  className="cursor-pointer rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-1 text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                  title={sortOrder === "asc" ? "升序" : "降序"}
                >
                  {sortOrder === "asc" ? (
                    <ArrowUp className="h-4 w-4" />
                  ) : (
                    <ArrowDown className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={requestHomeTour}
                className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 py-1.5 text-xs text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                title="重新查看新手引导"
              >
                <CircleHelp className="h-3.5 w-3.5" />
                新手引导
              </button>
              <button
                onClick={() => setComposerOpen(true)}
                data-onboarding-id="create-project"
                className="btn-primary cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                新建项目
              </button>
            </div>
          </div>
        </section>

        {loading ? (
          <div
            data-onboarding-id="project-list"
            className="surface flex items-center justify-center py-28"
          >
            <div className="text-[var(--color-text-secondary)] text-sm">
              加载中...
            </div>
          </div>
        ) : projects.length === 0 ? (
          <div
            data-onboarding-id="project-list"
            className="surface flex flex-col items-center justify-center px-6 py-28 text-center"
          >
            <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-lg bg-[var(--color-accent-soft)]">
              <Film className="h-7 w-7 text-[var(--color-accent)]" />
            </div>
            <h2 className="mb-8 text-lg font-semibold text-[var(--color-text-primary)]">
              暂无项目
            </h2>
          </div>
        ) : (
          <div
            data-onboarding-id="project-list"
            className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
          >
            {projects.map((project) => (
              <ProjectCard
                key={project.projectId}
                project={project}
                onOpen={handleOpen}
                onDelete={handleDelete}
                formatDate={formatDate}
              />
            ))}
          </div>
        )}
      </main>

      <ProjectComposer
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
      />
      <ModelConfigModal
        open={configModalOpen}
        onClose={() => {
          setConfigModalOpen(false);
          refreshModelConfig();
        }}
      />
      <HomeTour />
    </div>
  );
}
