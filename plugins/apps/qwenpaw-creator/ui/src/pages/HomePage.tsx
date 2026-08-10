import { useEffect, useState, useCallback, memo } from "react";
import { Modal, message, Tooltip } from "antd";
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
import { useRouter, useSearchParams } from "@/routing/navigation";
import ModelBadges from "@/components/creator/ModelBadges";
import ModelConfigModal from "@/components/creator/ModelConfigModal";
import { SCENARIO_OPTIONS } from "@/components/creator/useProjectLaunch";
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
import LanguageToggle from "@/components/common/LanguageToggle";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

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
  const { t } = useTranslation();
  var projectScenarioLabel = t("home.notSet");
  if (project.scenario !== undefined) {
    const found = SCENARIO_OPTIONS.find(
      (option) => option.key === project.scenario,
    );
    projectScenarioLabel = found ? t(found.labelKey) : project.scenario;
  }
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
              aria-label={t("home.previewFinal", { name: project.name })}
              className="flex h-6 shrink-0 cursor-pointer items-center gap-1 rounded bg-white px-2 text-sm font-medium leading-6 text-[#353332] transition-colors hover:text-[var(--color-accent)]"
            >
              <MaskIcon src={previewEyeIcon} size={16} />
              {t("common.preview")}
            </button>
          )}
        </div>
        <p className="line-clamp-2 min-h-[36px] text-xs leading-[18px] text-[var(--color-text-tertiary)]">
          {project.description}
        </p>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs leading-[18px] text-[var(--color-text-tertiary)]">
        <div className="flex min-w-0 items-center gap-1.5">
          <span>{projectScenarioLabel}</span>
          <span>{project.aspectRatio}</span>
          <span>{project.resolution}</span>
        </div>
        <span
          className="shrink-0 text-[var(--color-text-tertiary)]"
          title={t("home.createdAt") + " " + formatDate(project.createdAt)}
        >
          {formatDate(project.updatedAt)}
        </span>
        {/* Export moved to the plan page; the only card action left is a
            muted always-visible delete icon that reddens on hover only. */}
        <button
          type="button"
          aria-label={t("home.deleteProject", { name: project.name })}
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

const SORT_OPTIONS: { value: SortField; labelKey: string }[] = [
  { value: "updated_at", labelKey: "home.sortByUpdate" },
  { value: "created_at", labelKey: "home.sortByCreate" },
  { value: "name", labelKey: "home.sortByName" },
];

type HomeView = "create" | "projects";

const HOME_VIEWS: { key: HomeView; labelKey: string; icon: string }[] = [
  { key: "create", labelKey: "home.startCreating", icon: tabCreateIcon },
  { key: "projects", labelKey: "home.myProjects", icon: tabProjectsIcon },
];

export default function HomePage() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
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
        message.error(t("home.loadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [sortBy, sortOrder],
  );

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);

  // Set which view to display based on a search parameter. Strip the param
  // after consuming it, but bail when it's absent so the strip-induced
  // searchParams change doesn't re-run setView a second time.
  useEffect(() => {
    const raw = searchParams.get("view");
    if (raw === null) return;
    const viewParam: HomeView = raw === "projects" ? "projects" : "create";
    setView(viewParam);
    const next = new URLSearchParams(searchParams);
    next.delete("view");
    const query = next.toString();
    router.replace(query ? `/?${query}` : "/");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const handleOpen = useCallback(
    (id: string) => {
      router.push(`/project/${id}/plan`);
    },
    [router],
  );

  const handleDelete = useCallback(
    (project: ProjectSummary) => {
      Modal.confirm({
        title: t("home.deleteConfirm"),
        content: t("home.deleteConfirmContent", { name: project.name }),
        okText: t("common.delete"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await deleteProject(project.projectId);
            message.success(t("home.deleteSuccess"));
            fetchProjects();
          } catch {
            message.error(t("home.deleteFailed"));
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
    const locale = i18n.language === "zh" ? "zh-CN" : "en-US";
    return date.toLocaleDateString(locale, {
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
            aria-label={t("home.homeView")}
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
                {t(item.labelKey)}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <Tooltip title={t("nav.replayTour")}>
              <button
                type="button"
                onClick={requestHomeTour}
                className="icon-button shrink-0"
                aria-label={t("nav.replayTour")}
              >
                <CircleHelp className="h-3.5 w-3.5" />
              </button>
            </Tooltip>
            <LanguageToggle className="icon-button shrink-0 text-[11px] font-semibold" />
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
              {t("home.startCreatingDesc")}
              <br />
              {t("home.startCreatingDesc2")}
            </p>

            <div className="hero-fade-up mt-[34px] w-full [animation-delay:0.16s]">
              {!llmReady && (
                <button
                  type="button"
                  onClick={() => setConfigModalOpen(true)}
                  className="mb-3 flex w-full flex-wrap items-center gap-2 rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)]/70 px-3 py-2 text-left transition-colors hover:bg-[var(--color-warning-soft)]"
                >
                  <span className="text-xs font-semibold text-[var(--color-warning)]">
                    {t("home.notConfiguredLlm")}
                  </span>
                  <span className="min-w-0 flex-1 text-[11px] text-[var(--color-text-secondary)]">
                    {t("home.llmRequiredDesc")}
                  </span>
                  <span className="shrink-0 text-[11px] font-semibold text-[var(--color-accent)]">
                    {t("home.configureNow")}
                  </span>
                </button>
              )}
              <HeroComposerCard />
            </div>

            {/* Bundled example projects; hidden when the catalogue is empty. */}
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
                  {t("home.notConfiguredLlm")}
                </span>
                <span className="min-w-0 flex-1 text-[11px] text-[var(--color-text-secondary)]">
                  {t("home.llmRequiredDesc")}
                </span>
                <span className="shrink-0 text-[11px] font-semibold text-[var(--color-accent)]">
                  {t("home.configureNow")}
                </span>
              </button>
            )}
            <section className="flex items-center justify-between gap-3 py-4">
              <h1 className="text-xl font-medium leading-6 text-[var(--color-text-primary)]">
                {t("home.myProjects")}
              </h1>
              <div className="flex items-center gap-3">
                <select
                  value={sortBy}
                  onChange={handleSortChange}
                  aria-label={t("home.sortBy")}
                  className="cursor-pointer rounded-md border border-[#EAE9E7] bg-white px-3 py-1 text-sm font-medium leading-6 text-[var(--color-text-secondary)] outline-none focus:border-[var(--color-accent)]"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleSortOrderToggle}
                  className="cursor-pointer rounded-md border border-[#EAE9E7] bg-white p-1.5 text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                  title={
                    sortOrder === "asc"
                      ? t("home.ascending")
                      : t("home.descending")
                  }
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
                  {t("home.importProject")}
                </button>
              </div>
            </section>

            {loading ? (
              <div
                data-onboarding-id="project-list"
                className="flex items-center justify-center rounded-lg border border-[#EAE9E7] bg-white py-28"
              >
                <div className="text-sm text-[var(--color-text-secondary)]">
                  {t("common.loading")}
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
                  {t("home.noProjects")}
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
            {t("home.startCreating")}
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
          previewProject
            ? `${previewProject.name} · ${t("common.preview")}`
            : t("common.preview")
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
