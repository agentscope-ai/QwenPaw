import { useEffect, useMemo, useState } from "react";
import { Segmented } from "antd";
import {
  Activity,
  FolderSearch,
  LayoutList,
  Palette,
  Plus,
} from "lucide-react";
import { navigate, useSearchParams } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { AgentDock, SelectionToolbar } from "@/components/agent";
import DemoTopNav from "@/components/blueprint/DemoTopNav";
import StructureArea from "@/components/blueprint/StructureArea";
import RoughCutStrip from "@/components/blueprint/RoughCutStrip";
import ScriptDrawer from "@/components/blueprint/ScriptDrawer";
import PreproductionDrawer, {
  type PreproductionTab,
} from "@/components/blueprint/PreproductionDrawer";
import {
  DEMO_PROJECT_ID,
  SCENARIOS,
  buildDemoProject,
  type DetailData,
  type EpisodeScript,
  type ScenarioKey,
} from "@/components/blueprint/demoData";

/**
 * Blueprint demo: the real Creator stack (router, stores, antd, AgentDock)
 * rendering the redesigned "项目蓝图" IA with typed mock data. The narrative
 * structure fills the first screen; scripts and pre-production artifacts are
 * progressive-disclosure drawers instead of stacked scrolling sections.
 */
export default function BlueprintDemoPage() {
  const query = useSearchParams();
  const initialScenario = (query.get("sc") as ScenarioKey) || "drama";
  const [scenarioKey, setScenarioKey] = useState<ScenarioKey>(
    SCENARIOS.some((item) => item.key === initialScenario)
      ? initialScenario
      : "drama",
  );
  const scenario = useMemo(
    () => SCENARIOS.find((item) => item.key === scenarioKey)!,
    [scenarioKey],
  );
  const [selectedEpisode, setSelectedEpisode] = useState<EpisodeScript | null>(
    null,
  );
  const [scriptOpen, setScriptOpen] = useState(false);
  const [prepOpen, setPrepOpen] = useState(false);
  const [prepTab, setPrepTab] = useState<PreproductionTab>("visual");
  const [prepFocus, setPrepFocus] = useState<DetailData | null>(null);

  useEffect(() => {
    // Seed the real snapshot store so AgentDock (and the drill-down PlanPage)
    // read an authoritative project; failed background polls only degrade.
    useProjectSnapshotStore.setState({
      projectId: DEMO_PROJECT_ID,
      project: buildDemoProject(scenario),
      generation: 1,
      etag: `demo-${scenario.key}`,
      syncStatus: "healthy",
    });
  }, [scenario]);

  useEffect(() => {
    setScriptOpen(false);
    setPrepOpen(false);
    setSelectedEpisode(null);
    setPrepTab(scenario.visual ? "visual" : "research");
  }, [scenario]);

  const openScript = (episode: EpisodeScript) => {
    setSelectedEpisode(episode);
    setScriptOpen(true);
    // 选中即成为创作助手的上下文引用（真实 interaction store）
    useCreatorInteractionStore.getState().select(`node:${episode.name}`);
  };
  const openDetail = (detail: DetailData) => {
    setPrepFocus(detail);
    setPrepTab(detail.type === "visual" ? "visual" : "research");
    setPrepOpen(true);
    useCreatorInteractionStore.getState().select(`blueprint:${detail.title}`);
  };
  const openTimeline = (episode: EpisodeScript) => {
    navigate(
      `/blueprint-demo/${DEMO_PROJECT_ID}/plan?sc=${scenario.key}&ep=${episode.id}`,
    );
  };
  const pendingVisual = scenario.visual?.filter((item) => item.pending) ?? [];
  const pendingResearch = scenario.research.filter(
    (item) => item.tone === "wait",
  );

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
        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          <main className="panel-enter relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[var(--color-bg-layout)]">
            {/* 页头：形态 chips + 场景切换 + 结构操作 */}
            <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/60 px-5 py-3 backdrop-blur">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold text-[var(--color-text-primary)]">
                  项目蓝图
                </h2>
                {scenario.chips.map((chip) => (
                  <span
                    key={chip.text}
                    className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                      chip.warn
                        ? "border-[rgba(247,144,9,.5)] bg-[var(--color-warning-soft)] text-[var(--color-warning)]"
                        : "border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)]"
                    }`}
                  >
                    {chip.text}
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Segmented
                  size="small"
                  value={scenarioKey}
                  onChange={(value) => setScenarioKey(value as ScenarioKey)}
                  options={SCENARIOS.map((item) => ({
                    label: item.label,
                    value: item.key,
                  }))}
                />
                {scenario.structureActions ? (
                  <button type="button" className="btn-secondary">
                    <Plus className="h-3.5 w-3.5" />
                    插入节点
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => openTimeline(scenario.single!)}
                    className="inline-flex items-center gap-2 rounded-[10px] bg-[var(--color-text-primary)] px-5 py-2.5 text-sm font-bold leading-none text-[var(--color-bg-primary)] shadow-[0_2px_8px_rgba(0,0,0,.2)] transition-all hover:-translate-y-px hover:opacity-90 hover:shadow-[0_4px_14px_rgba(0,0,0,.25)]"
                  >
                    <LayoutList className="h-4 w-4" />
                    进入时间线编辑
                  </button>
                )}
              </div>
            </header>

            {/* 首屏 = 叙事结构本身；剧本与前置产物点开即出，不再纵向堆叠 */}
            <div className="min-h-0 flex-1 p-4">
              <StructureArea
                scenario={scenario}
                selectedId={selectedEpisode?.id ?? ""}
                onSelect={openScript}
                onOpenTimeline={openTimeline}
                onOpenDetail={openDetail}
              />
            </div>

            {/* 粗剪预览带：由既有产物（镜头视频/分镜图/设计图）零成本组装 */}
            <RoughCutStrip scenario={scenario} onSelect={openScript} />

            {/* 底部：前置产物入口条（渐进式披露的唯一常驻入口） */}
            <footer className="flex shrink-0 flex-wrap items-center gap-2.5 border-t border-[var(--color-border)] bg-[var(--color-bg-primary)]/70 px-5 py-2.5 backdrop-blur">
              <span className="flex min-w-0 items-center gap-2.5">
                <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
                  <Activity className="h-3.5 w-3.5 text-[var(--color-primary,#3b82f6)]" />
                  正在进行
                </span>
                {scenario.running.length > 0 ? (
                  scenario.running.map((task) => (
                    <span
                      key={task.label}
                      className="inline-flex items-center gap-2 rounded-full border border-[rgba(59,130,246,.3)] bg-[rgba(59,130,246,.06)] px-3 py-1 text-[11px] font-medium text-[var(--color-text-secondary)]"
                    >
                      {task.label}
                      {task.progress != null && (
                        <>
                          <span className="h-1 w-16 overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
                            <span
                              className="block h-full rounded-full bg-[var(--color-primary,#3b82f6)] transition-[width] duration-500"
                              style={{ width: `${task.progress}%` }}
                            />
                          </span>
                          <span className="tabular-nums text-[var(--color-primary,#3b82f6)]">
                            {task.progress}%
                          </span>
                        </>
                      )}
                    </span>
                  ))
                ) : (
                  <span className="text-[11px] text-[var(--color-text-tertiary)]">
                    {scenario.runningEmpty ?? "暂无进行中的生产任务"}
                  </span>
                )}
              </span>
              <span className="mx-1 hidden h-5 w-px bg-[var(--color-border)] sm:block" />
              {scenario.visual && (
                <button
                  type="button"
                  onClick={() => {
                    setPrepFocus(null);
                    setPrepTab("visual");
                    setPrepOpen(true);
                  }}
                  className="group inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3.5 py-1.5 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                >
                  <Palette className="h-3.5 w-3.5" />
                  视觉开发 · {scenario.visual.length} 项
                  {pendingVisual.length > 0 && (
                    <span className="rounded-full bg-[var(--color-warning-soft)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-warning)]">
                      {pendingVisual.length} 待确认
                    </span>
                  )}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setPrepFocus(null);
                  setPrepTab("research");
                  setPrepOpen(true);
                }}
                className="group inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3.5 py-1.5 text-xs font-semibold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              >
                <FolderSearch className="h-3.5 w-3.5" />
                调研与素材 · {scenario.research.length} 项
                {pendingResearch.length > 0 && (
                  <span className="rounded-full bg-[var(--color-warning-soft)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-warning)]">
                    {pendingResearch.length} 待确认
                  </span>
                )}
              </button>
              <span className="ml-auto text-[11px] text-[var(--color-text-tertiary)]">
                点击叙事节点审阅剧本 · 悬停节点可直达时间线
              </span>
            </footer>

            {/* 内嵌面板：只覆盖工作区，AgentDock 始终可见；选中对象已作为引用挂入助手上下文 */}
            <ScriptDrawer
              episode={selectedEpisode}
              open={scriptOpen}
              visualPool={scenario.visual}
              onClose={() => setScriptOpen(false)}
              onOpenTimeline={openTimeline}
              onOpenVisual={(item) => openDetail(item.detail)}
            />
            <PreproductionDrawer
              open={prepOpen}
              tab={prepTab}
              visual={scenario.visual}
              research={scenario.research}
              focusDetail={prepFocus}
              onClose={() => {
                setPrepOpen(false);
                setPrepFocus(null);
              }}
              onTabChange={setPrepTab}
            />
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
