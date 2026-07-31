import { useEffect, useState, useCallback, memo } from "react";
import { Modal, message } from "antd";
import { Film, ArrowUp, ArrowDown, CircleHelp, Trash2 } from "lucide-react";
import logoMarkUrl from "@/assets/design/logo-mark.png";
import tabCreateIcon from "@/assets/design/icon-tab-create.svg";
import tabProjectsIcon from "@/assets/design/icon-tab-projects.svg";
import previewEyeIcon from "@/assets/design/icon-eye-preview.svg";
import importProjectIcon from "@/assets/design/icon-import-project.svg";
import type { ModelConfigData, ProjectSummary } from "@/contracts/creator";
import {
  deleteProject,
  getModelConfig,
  listProjects,
  getArtifactVersionMediaUrl,
} from "@/api/creator";
import { useRouter } from "@/routing/navigation";
import ModelBadges from "@/components/creator/ModelBadges";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import {
  SCENARIO_OPTIONS,
  CONTENT_TYPE_OPTIONS,
} from "@/components/creator/useProjectLaunch";
import {
  SEGMENTED_TRACK_CLASS,
  segmentedItemClass,
} from "@/components/common/segmentedTabs";
import MaskIcon from "@/components/common/MaskIcon";
import HeroBackground from "@/components/creator/HeroBackground";
import HeroComposerCard from "@/components/creator/HeroComposerCard";
import HeroTitle from "@/components/creator/HeroTitle";
import InspirationExamples from "@/components/creator/InspirationExamples";
import { HomeTour } from "@/components/onboarding";
import { useOnboardingStore } from "@/store/onboardingStore";
import { ProjectImporter } from "@/components/creator/ProjectImportExport";

interface ProjectCardProps {
  project: ProjectSummary;
  onOpen: (id: string) => void;
  onDelete: (project: ProjectSummary) => void;
  onPreview: (project: ProjectSummary) => void;
  formatDate: (dateStr: string) => string;
}

/** Text-only project card from the design draft. */
const ProjectCard = memo(function ProjectCard({
  project,
  onOpen,
  onDelete,
  onPreview,
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
  // Content type is an editing-only concept.
  const showContentType =
    project.scenario === "video_edit" && Boolean(project.contentType);
  const canPreview = Boolean(project.finalVideoVersionId);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(project.projectId)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpen(project.projectId);
      }}
      className="group relative flex w-full cursor-pointer flex-col gap-5 overflow-hidden rounded-lg border border-[#EAE9E7] bg-white p-4 transition-colors hover:bg-[rgba(243,243,242,0.3)]"
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-1">
          <h3 className="min-w-0 flex-1 truncate text-sm font-medium leading-6 text-[var(--color-text-primary)]">
            {project.name}
          </h3>
          {canPreview && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onPreview(project);
              }}
              aria-label={`预览 ${project.name} 成片`}
              className="flex h-6 shrink-0 cursor-pointer items-center gap-1 rounded bg-white px-2 text-sm font-medium leading-6 text-[#353332] transition-colors hover:text-[var(--color-accent)]"
            >
              <MaskIcon src={previewEyeIcon} size={16} />
              预览
            </button>
          )}
        </div>
        <p className="line-clamp-2 min-h-[36px] text-xs leading-[18px] text-[var(--color-text-tertiary)]">
          {project.description}
        </p>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs leading-[18px]">
        <div className="flex min-w-0 items-center gap-1.5">
          {showContentType && (
            <>
              <p className="min-w-0 truncate">
                <span className="font-medium text-[var(--color-text-secondary)]">
                  类型：
                </span>
                <span className="text-[var(--color-text-tertiary)]">
                  {projectContentType}
                </span>
              </p>
              <span className="h-3 w-px shrink-0 bg-[#E3E2E2]" />
            </>
          )}
          <div className="flex shrink-0 items-center gap-3 text-[var(--color-text-tertiary)]">
            <span>{projectScenarioLabel}</span>
            <span>{project.aspectRatio}</span>
            <span>{project.resolution}</span>
          </div>
        </div>
        <span
          className="shrink-0 text-[var(--color-text-tertiary)]"
          title={`创建于 ${formatDate(project.createdAt)}`}
        >
          {formatDate(project.updatedAt)}
        </span>
        {/* Export moved to the plan page; the only card action left is a
            muted always-visible delete icon that reddens on hover only. */}
        <button
          type="button"
          aria-label={`删除 ${project.name}`}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(project);
          }}
          className="flex h-[18px] w-[18px] shrink-0 cursor-pointer items-center justify-center text-[var(--color-text-tertiary)] transition-colors hover:text-[var(--color-danger)]"
        >
          <Trash2 className="h-3.5 w-3.5" />
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

type HomeView = "create" | "projects";

const HOME_VIEWS: { key: HomeView; label: string; icon: string }[] = [
  { key: "create", label: "开始创作", icon: tabCreateIcon },
  { key: "projects", label: "我的项目", icon: tabProjectsIcon },
];

export default function HomePage() {
  const router = useRouter();
  const [view, setView] = useState<HomeView>("create");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [previewProject, setPreviewProject] = useState<ProjectSummary | null>(
    null,
  );
  const [importerOpen, setImporterOpen] = useState(false);
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
    <div className="relative min-h-full app-shell">
      {/* The glow runs behind the borderless header so the bar reads as one
          piece with the page, per the draft. */}
      {view === "create" && <HeroBackground />}
      <header
        className={`relative z-10 ${
          view === "create"
            ? ""
            : "border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]"
        }`}
      >
        <div className="flex h-[72px] items-center justify-between px-5">
          <div className="flex items-center gap-2">
            <img src={logoMarkUrl} alt="" width={38} height={38} />
            <span className="text-xl font-medium leading-6 text-[var(--color-text-primary)]">
              QwenPaw Creator
            </span>
          </div>
          <div
            role="tablist"
            aria-label="首页视图"
            className={`absolute left-1/2 -translate-x-1/2 ${SEGMENTED_TRACK_CLASS}`}
          >
            {HOME_VIEWS.map((item) => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={view === item.key}
                data-onboarding-id={
                  item.key === "projects" ? "projects-tab" : undefined
                }
                onClick={() => setView(item.key)}
                className={segmentedItemClass(view === item.key)}
              >
                <MaskIcon src={item.icon} size={18} />
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={requestHomeTour}
              className="flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center text-[#989796] transition-colors hover:text-[var(--color-accent)]"
              title="重新查看新手引导"
              aria-label="重新查看新手引导"
            >
              <CircleHelp className="h-4 w-4" />
            </button>
            <ModelBadges />
          </div>
        </div>
      </header>

      {view === "create" ? (
        <main className="relative flex min-h-[calc(100vh-72px)] flex-col">
          {/* 840px of drafted composer width plus 24px gutters. */}
          <div className="relative z-[1] mx-auto flex w-full max-w-[888px] flex-1 flex-col items-center justify-center px-6 pb-[2vh] pt-[10vh]">
            <div className="hero-fade-up">
              <HeroTitle />
            </div>
            <p className="hero-fade-up mt-6 w-[624px] max-w-full text-center text-sm leading-7 text-[#3D3D3D] [animation-delay:0.08s]">
              开始创作吧！请将目标、素材和限制交给
              Agent。资料输入是一次性的启动动作。
              <br />
              进入项目后，它们会变成可管理、可引用、可追踪的项目资产。
            </p>

            <div className="hero-fade-up mt-[34px] w-full [animation-delay:0.16s]">
              {!llmReady && (
                <button
                  type="button"
                  onClick={() => setConfigModalOpen(true)}
                  className="mb-3 flex w-full flex-wrap items-center gap-2 rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)]/70 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]"
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
              <HeroComposerCard />
            </div>

            {/* Hidden until curated content ships. */}
            <div className="hero-fade-up mt-8 w-full [animation-delay:0.24s]">
              <InspirationExamples />
            </div>
          </div>
        </main>
      ) : (
        <main className="min-h-[calc(100vh-72px)] bg-[linear-gradient(180deg,#FFFFFF_31%,#FAFAFA_43%)]">
          <div className="mx-auto w-full max-w-[1360px] px-5">
            {!llmReady && (
              <button
                type="button"
                onClick={() => setConfigModalOpen(true)}
                className="mt-4 flex w-full flex-wrap items-center gap-2 rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)]/50 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]"
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
            <section className="flex items-center justify-between gap-3 py-4">
              <h1 className="text-xl font-medium leading-6 text-[var(--color-text-primary)]">
                我的项目
              </h1>
              <div className="flex items-center gap-3">
                <select
                  value={sortBy}
                  onChange={handleSortChange}
                  aria-label="排序方式"
                  className="cursor-pointer rounded-md border border-[#EAE9E7] bg-white px-3 py-1 text-sm font-medium leading-6 text-[var(--color-text-secondary)] outline-none focus:border-[var(--color-accent)]"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleSortOrderToggle}
                  className="cursor-pointer rounded-md border border-[#EAE9E7] bg-white p-1.5 text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                  title={sortOrder === "asc" ? "升序" : "降序"}
                >
                  {sortOrder === "asc" ? (
                    <ArrowUp className="h-4 w-4" />
                  ) : (
                    <ArrowDown className="h-4 w-4" />
                  )}
                </button>
                <button
                  onClick={() => setImporterOpen(true)}
                  data-onboarding-id="import-project"
                  className="flex cursor-pointer items-center gap-2 rounded-md border border-[#EAE9E7] bg-white px-3 py-1 text-sm font-medium leading-6 text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                >
                  <MaskIcon src={importProjectIcon} size={20} />
                  导入项目
                </button>
              </div>
            </section>

            {loading ? (
              <div
                data-onboarding-id="project-list"
                className="flex items-center justify-center rounded-lg border border-[#EAE9E7] bg-white py-28"
              >
                <div className="text-sm text-[var(--color-text-secondary)]">
                  加载中...
                </div>
              </div>
            ) : projects.length === 0 ? (
              <div
                data-onboarding-id="project-list"
                className="flex flex-col items-center justify-center rounded-lg border border-[#EAE9E7] bg-white px-6 py-28 text-center"
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
                className="grid grid-cols-1 gap-4 pb-56 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
              >
                {projects.map((project) => (
                  <ProjectCard
                    key={project.projectId}
                    project={project}
                    onOpen={handleOpen}
                    onDelete={handleDelete}
                    onPreview={setPreviewProject}
                    formatDate={formatDate}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Cards dissolve into the page bottom before reaching the pill. */}
          <div
            aria-hidden="true"
            className="pointer-events-none fixed inset-x-0 bottom-0 z-30 h-[240px] bg-[linear-gradient(180deg,rgba(250,250,250,0)_0%,rgba(250,250,250,0.9)_45%,#FAFAFA_100%)]"
          />
          <button
            type="button"
            onClick={() => setView("create")}
            className="fixed bottom-[96px] left-1/2 z-40 flex -translate-x-1/2 cursor-pointer items-center gap-[15px] rounded-full bg-[#FF9D4D] px-8 py-2 text-2xl font-medium leading-[44px] text-white shadow-[0_5px_38px_rgba(146,102,0,0.35),inset_0_1px_1px_rgba(255,255,255,0.1),inset_0_-2px_2px_rgba(0,0,0,0.05)] transition-transform hover:scale-[1.03]"
          >
            <MaskIcon src={tabCreateIcon} size={32} />
            开始创作
          </button>
        </main>
      )}

      <Modal
        open={previewProject !== null}
        onCancel={() => setPreviewProject(null)}
        footer={null}
        destroyOnHidden
        centered
        width={720}
        title={
          previewProject ? `${previewProject.name} · 成片预览` : "成片预览"
        }
      >
        {previewProject?.finalVideoVersionId && (
          <video
            src={getArtifactVersionMediaUrl(previewProject.finalVideoVersionId)}
            controls
            autoPlay
            className="max-h-[70vh] w-full rounded-md bg-black"
          />
        )}
      </Modal>
      <ModelConfigModal
        open={configModalOpen}
        onClose={() => {
          setConfigModalOpen(false);
          refreshModelConfig();
        }}
      />
      <ProjectImporter
        open={importerOpen}
        onClose={() => setImporterOpen(false)}
        onImported={() => fetchProjects()}
      />
      <HomeTour />
    </div>
  );
}
