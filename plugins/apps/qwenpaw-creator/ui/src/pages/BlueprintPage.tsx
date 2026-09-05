import { useEffect, useMemo, useState } from "react";
import { FolderSearch, Palette } from "lucide-react";
import { MenuUnfoldOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useWorkGraphStore } from "@/store/workGraphStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { selectNarrativeShape } from "@/selectors/timelineElementSelectors";
import {
  isVoiceOnlyVisualEntity,
  selectResearchSlots,
  selectTimelineSummaries,
} from "@/selectors/blueprintSelectors";
import BlueprintStructureArea from "@/components/blueprint/BlueprintStructureArea";
import BlueprintScriptPanel from "@/components/blueprint/BlueprintScriptPanel";
import BlueprintRoughCutStrip from "@/components/blueprint/BlueprintRoughCutStrip";
import ProjectExportActions from "@/components/creator/ProjectExportActions";
import BlueprintPrepDrawer, {
  type PrepFocus,
  type PreproductionTab,
} from "@/components/blueprint/BlueprintPrepDrawer";
import PageLoadError from "@/components/PageLoadError";
import PageSkeleton from "@/components/PageSkeleton";

/**
 * Project blueprint — the project's default landing view (plan §4.2).
 * Renders inside ProjectLayout's Outlet: TopNav / AgentDock / polling are
 * provided by the layout, and inline panels only cover the workspace column
 * so the dock stays usable (hard rule §4).
 */
export default function BlueprintPage() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const query = useSearchParams();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === id ? state.project : null,
  );
  const syncStatus = useProjectSnapshotStore((state) => state.syncStatus);
  const syncError = useProjectSnapshotStore((state) => state.syncError);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const workGraph = useWorkGraphStore((state) =>
    state.projectId === id ? state.graph : null,
  );

  const shape = useMemo(() => selectNarrativeShape(project), [project]);
  const summaries = useMemo(
    () => (project ? selectTimelineSummaries(project) : []),
    [project],
  );
  const researchSlots = useMemo(
    () => (project ? selectResearchSlots(project) : []),
    [project],
  );

  const [selectedTimelineId, setSelectedTimelineId] = useState<string | null>(
    null,
  );
  const sidebarOpen = useAgentDockUiStore((state) => state.open);
  const setSidebarOpen = useAgentDockUiStore((state) => state.setOpen);
  const [scriptOpen, setScriptOpen] = useState(false);
  const [prepOpen, setPrepOpen] = useState(false);
  const [prepTab, setPrepTab] = useState<PreproductionTab>("visual");
  const [prepFocus, setPrepFocus] = useState<PrepFocus | null>(null);

  // Deep link from a Review locator (?timeline=…): select + open the node.
  const timelineFromQuery = query.get("timeline");
  useEffect(() => {
    if (!project || !timelineFromQuery) return;
    if (!project.timelines.items[timelineFromQuery]) return;
    setSelectedTimelineId(timelineFromQuery);
    setScriptOpen(true);
    useCreatorInteractionStore
      .getState()
      .select(`timeline:${timelineFromQuery}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timelineFromQuery, project ? 1 : 0]);

  const openScript = (timelineId: string) => {
    setSelectedTimelineId(timelineId);
    setScriptOpen(true);
    // 选中即引用：the node becomes the assistant's context reference.
    useCreatorInteractionStore.getState().select(`timeline:${timelineId}`);
  };
  const openTimeline = (timelineId: string) => {
    navigate(`/project/${id}/t/${encodeURIComponent(timelineId)}/plan`);
  };
  const openElement = (timelineId: string, elementId: string) => {
    navigate(
      `/project/${id}/t/${encodeURIComponent(
        timelineId,
      )}/plan?element=${encodeURIComponent(elementId)}`,
    );
  };
  const openVisualEntity = (entityId: string) => {
    setPrepFocus({ type: "visual", entityId });
    setPrepTab("visual");
    setPrepOpen(true);
    useCreatorInteractionStore.getState().select(`visual-entity:${entityId}`);
  };
  const openResearch = (slotId: string) => {
    setPrepFocus({ type: "research", slotId });
    setPrepTab("research");
    setPrepOpen(true);
    useCreatorInteractionStore.getState().select(`research:${slotId}`);
  };
  const openSource = (sourceId: string) => {
    setPrepFocus({ type: "source", sourceId });
    setPrepTab("research");
    setPrepOpen(true);
  };

  if (!project) {
    if (syncStatus === "invalid" || syncStatus === "not_found") {
      return (
        <PageLoadError
          message={syncError || t("assets.projectReadError")}
          retry={() => void pollOnce(id)}
        />
      );
    }
    return <PageSkeleton type="editor" />;
  }

  const sourceCount = project.sources.sources.order.length;
  const pendingVisual = project.visual.entities.order.filter((entityId) => {
    const entity = project.visual.entities.items[entityId];
    if (!entity) return false;
    // Voice-only roles (enrolled voice, no visual variants) have no
    // portrait to confirm.
    if (isVoiceOnlyVisualEntity(entity)) return false;
    return !(
      entity.selected_artifact_version_id ||
      entity.variants.order.some(
        (variantId) =>
          entity.variants.items[variantId]?.selected_artifact_version_id,
      )
    );
  }).length;
  const runningNodes = (workGraph?.nodes ?? []).filter(
    (node) => node.status === "running",
  );

  return (
    <div
      data-blueprint-page
      className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[var(--color-bg-layout)]"
    >
      {/* Header (design 83:13383): back + page title left, pre-production
          entries right; export actions live on the plan page header. */}
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/60 px-5 py-3 backdrop-blur">
        <div className="flex min-w-0 items-center gap-2.5">
          {!sidebarOpen && (
            <button
              type="button"
              data-sidebar-expand
              title={t("plan.expandSidebar")}
              aria-label={t("plan.expandSidebar")}
              onClick={() => setSidebarOpen(true)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] transition hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] dark:bg-[var(--color-bg-elevated)]"
            >
              <MenuUnfoldOutlined className="text-base" />
            </button>
          )}
          <h2 className="truncate text-sm font-medium text-[var(--color-text-primary)]">
            {t("blueprint.pageTitle")}
          </h2>
        </div>
        <span className="flex flex-wrap items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => {
              setPrepFocus(null);
              setPrepTab("research");
              setPrepOpen(true);
            }}
            className="btn-secondary"
          >
            <FolderSearch className="h-3.5 w-3.5" />
            {t("blueprint.researchAndSources")}
            {researchSlots.length + sourceCount > 0 && (
              <span className="text-[var(--color-text-tertiary)]">
                {researchSlots.length + sourceCount}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              setPrepFocus(null);
              setPrepTab("visual");
              setPrepOpen(true);
            }}
            className="btn-secondary"
          >
            <Palette className="h-3.5 w-3.5" />
            {t("blueprint.visualDev")}
            {pendingVisual > 0 && (
              <span className="rounded-full bg-[var(--color-warning-soft)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-warning)]">
                {t("blueprint.pendingCount", { count: pendingVisual })}
              </span>
            )}
          </button>
          {/* 下载/导出 + 导出互动包 (design 84:30317) live on the blueprint
              header, not the plan page. */}
          <ProjectExportActions project={project} />
        </span>
      </header>

      {/* First screen: single projects read as the script document itself
          (design 84:37778); multi-episode / branching keep the structure. */}
      {shape === "single" ? (
        <BlueprintScriptPanel
          project={project}
          projectId={id}
          timelineId={project.timelines.order[0] ?? null}
          open
          inline
          onClose={() => {}}
          onOpenTimeline={openTimeline}
          onOpenVisualEntity={openVisualEntity}
        />
      ) : (
        <div className="workspace-decor-grid min-h-0 flex-1 p-4">
          <BlueprintStructureArea
            project={project}
            shape={shape}
            summaries={summaries}
            selectedTimelineId={scriptOpen ? selectedTimelineId : null}
            onSelectTimeline={openScript}
            onOpenTimeline={openTimeline}
            onOpenElement={openElement}
            onOpenVisualEntity={openVisualEntity}
            onOpenResearch={openResearch}
            onOpenSource={openSource}
          />
        </div>
      )}

      <BlueprintRoughCutStrip project={project} onSelectTimeline={openScript} />

      {/* Bottom: production task status bar (design 83:13383). */}
      <footer className="flex shrink-0 flex-wrap items-center gap-2.5 border-t border-[var(--color-border)] bg-[var(--color-bg-primary)]/70 px-5 py-2.5 backdrop-blur">
        {runningNodes.length > 0 ? (
          runningNodes.slice(0, 3).map((node) => (
            <span
              key={node.id}
              className="inline-flex items-center gap-2 rounded-full border border-[rgba(59,130,246,.3)] bg-[rgba(59,130,246,.06)] px-3 py-1 text-[11px] font-medium text-[var(--color-text-secondary)]"
            >
              {node.label}
              {node.progress != null && (
                <>
                  <span className="h-1 w-16 overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
                    <span
                      className="block h-full rounded-full bg-[var(--color-primary,#3b82f6)] transition-[width] duration-500"
                      style={{
                        width: `${Math.round(node.progress * 100)}%`,
                      }}
                    />
                  </span>
                  <span className="tabular-nums text-[var(--color-primary,#3b82f6)]">
                    {Math.round(node.progress * 100)}%
                  </span>
                </>
              )}
            </span>
          ))
        ) : (
          <span className="text-xs text-[var(--color-text-tertiary)]">
            {t("blueprint.runningEmpty")}
          </span>
        )}
      </footer>

      {/* Inline panels: only the workspace column, AgentDock stays visible. */}
      {shape !== "single" && (
        <BlueprintScriptPanel
          project={project}
          projectId={id}
          timelineId={selectedTimelineId}
          open={scriptOpen}
          onClose={() => setScriptOpen(false)}
          onOpenTimeline={openTimeline}
          onOpenVisualEntity={openVisualEntity}
        />
      )}
      <BlueprintPrepDrawer
        project={project}
        projectId={id}
        open={prepOpen}
        tab={prepTab}
        focus={prepFocus}
        onClose={() => {
          setPrepOpen(false);
          setPrepFocus(null);
        }}
        onTabChange={setPrepTab}
      />
    </div>
  );
}
