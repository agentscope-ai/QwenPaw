import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { AgentDock, SelectionToolbar } from "@/components/agent";
import PageSkeleton from "@/components/PageSkeleton";
import DemoTopNav from "@/components/blueprint/DemoTopNav";
import {
  DEMO_PROJECT_ID,
  GRADS,
  SCENARIOS,
  buildDemoProject,
  type EpisodeScript,
  type ScenarioKey,
  type Tone,
} from "@/components/blueprint/demoData";

const PlanPage = lazy(() => import("@/pages/PlanPage"));

const DOT_TONE: Record<Tone, string> = {
  done: "bg-[var(--color-success)]",
  run: "bg-[var(--color-primary,#3b82f6)]",
  wait: "bg-[var(--color-warning)]",
  idle: "bg-[var(--color-border-strong)]",
};

/**
 * Demo wrapper around the REAL PlanPage. Episode switching lives in a left
 * collapsible rail (no extra top bar); returning to the blueprint goes
 * through the TopNav "项目蓝图" pill, so there is no semantic conflict with
 * the back-to-projects arrow next to the logo.
 */
export default function BlueprintDemoPlanPage() {
  const { id = DEMO_PROJECT_ID } = useParams();
  const query = useSearchParams();
  const scenarioKey = (query.get("sc") as ScenarioKey) || "drama";
  const scenario = useMemo(
    () => SCENARIOS.find((item) => item.key === scenarioKey) ?? SCENARIOS[0],
    [scenarioKey],
  );
  const episodes = useMemo<EpisodeScript[]>(() => {
    if (scenario.structure === "graph")
      return scenario.graph!.nodes.map((node) => node.ep);
    if (scenario.structure === "list")
      return scenario.episodes!.map((item) => item.ep);
    return [scenario.single!];
  }, [scenario]);
  const activeId = query.get("ep") ?? scenario.defaultEpisodeId;
  const [railCollapsed, setRailCollapsed] = useState(false);

  useEffect(() => {
    // Same seed as the blueprint page: direct links to this route also work.
    useProjectSnapshotStore.setState({
      projectId: id,
      project: buildDemoProject(scenario),
      generation: 1,
      etag: `demo-${scenario.key}`,
      syncStatus: "healthy",
    });
  }, [id, scenario]);

  const switchEpisode = (episode: EpisodeScript) => {
    useCreatorInteractionStore.getState().select(`node:${episode.name}`);
    navigate(
      `/blueprint-demo/${id}/plan?sc=${scenario.key}&ep=${episode.id}`,
      true,
    );
  };

  return (
    <div
      data-project-shell
      className="app-shell grid h-screen grid-rows-[58px_minmax(0,1fr)]"
    >
      <DemoTopNav
        navName={scenario.navName}
        navPreview={scenario.navPreview}
        active="blueprint"
        scenarioKey={scenario.key}
      />
      <div className="flex min-h-0 overflow-hidden">
        {/* 左侧剧集栏：可完全收起（收起后仅剩左缘悬浮把手，不占列宽） */}
        {!railCollapsed && (
          <aside className="flex min-h-0 w-[200px] shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-primary)]">
            <div className="flex shrink-0 items-center justify-between border-b border-[var(--color-border)] px-2 py-2">
              <span className="pl-1 text-[11px] font-bold text-[var(--color-text-secondary)]">
                剧集 · {episodes.length}
              </span>
              <button
                type="button"
                onClick={() => setRailCollapsed(true)}
                className="icon-button !h-7 !w-7"
                title="收起剧集栏"
              >
                <PanelLeftClose className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-1.5">
              {episodes.map((episode) => {
                const active = episode.id === activeId;
                return (
                  <button
                    key={episode.id}
                    type="button"
                    title={episode.synopsis}
                    onClick={() => switchEpisode(episode)}
                    className={`mx-1.5 mb-1 flex w-[calc(100%-12px)] items-center gap-2 rounded-lg px-1.5 py-1.5 text-left transition-colors ${
                      active
                        ? "bg-[var(--color-accent-soft)] shadow-[inset_0_0_0_1px_rgba(255,127,22,.25)]"
                        : "hover:bg-[var(--color-bg-secondary)]"
                    }`}
                  >
                    <span
                      className="h-9 w-7 shrink-0 rounded-md border border-[var(--color-border)]"
                      style={{
                        backgroundImage: GRADS[episode.cast[0]?.grad ?? "g1"],
                      }}
                    />
                    <span className="min-w-0 flex-1 leading-tight">
                      <span
                        className={`block truncate text-[11px] font-bold ${
                          active
                            ? "text-[var(--color-text-primary)]"
                            : "text-[var(--color-text-secondary)]"
                        }`}
                      >
                        {episode.name}
                      </span>
                      <span className="mt-0.5 flex items-center gap-1">
                        <span
                          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                            DOT_TONE[episode.status.tone]
                          }`}
                        />
                        <span className="truncate text-[10px] text-[var(--color-text-tertiary)]">
                          {episode.status.text}
                        </span>
                      </span>
                      {episode.status.progress != null && (
                        <span className="mt-1 block h-1 overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
                          <span
                            className="block h-full rounded-full bg-[var(--color-primary,#3b82f6)]"
                            style={{ width: `${episode.status.progress}%` }}
                          />
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </aside>
        )}

        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          {railCollapsed && (
            <button
              type="button"
              onClick={() => setRailCollapsed(false)}
              title="展开剧集栏"
              className="btn-secondary absolute left-5 top-[11px] z-20"
            >
              <PanelLeftOpen className="h-3.5 w-3.5" />
              剧集 · {episodes.length}
            </button>
          )}
          {/* 创作总纲已由项目蓝图（剧本/梗概）承载，Plan 页隐藏原折叠块；正式实现中直接移除 */}
          <style>{`[data-plan-page] [data-onboarding-id="creative-brief"] { display: none; }`}</style>
          <main className="panel-enter relative min-h-0 flex-1 overflow-hidden">
            <Suspense fallback={<PageSkeleton type="editor" />}>
              <PlanPage />
            </Suspense>
          </main>
        </div>
        <div className="flex min-h-0 shrink-0 flex-col">
          <div className="flex min-h-0 flex-1">
            <AgentDock sidebar />
          </div>
          <div
            data-detail-rail
            className="hidden min-h-0 shrink-0 basis-1/2 flex-col overflow-hidden border-t-2 border-[var(--color-border-strong)] bg-[var(--color-bg-layout)] [&:not(:empty)]:flex"
          />
        </div>
      </div>
      <SelectionToolbar />
    </div>
  );
}
