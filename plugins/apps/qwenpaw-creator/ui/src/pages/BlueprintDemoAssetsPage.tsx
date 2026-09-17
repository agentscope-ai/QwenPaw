import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  FileText,
  FolderSearch,
  Palette,
  Video,
  X,
} from "lucide-react";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { AgentDock, SelectionToolbar } from "@/components/agent";
import DemoTopNav from "@/components/blueprint/DemoTopNav";
import ScriptDrawer from "@/components/blueprint/ScriptDrawer";
import { DetailView } from "@/components/blueprint/PreproductionDrawer";
import { episodesOf } from "@/components/blueprint/RoughCutStrip";
import {
  DEMO_PROJECT_ID,
  GRADS,
  SCENARIOS,
  TONE_CHIP,
  TONE_TEXT,
  buildDemoProject,
  type DetailData,
  type EpisodeScript,
  type ScenarioKey,
} from "@/components/blueprint/demoData";

/**
 * Demo 资产库：全量库存视图，按归属分组（同一份 data model 的另一种投影）。
 * 与蓝图的关系：蓝图展示"与创作决策相关"的产物切片；资产库是完整库存 +
 * 管理入口，任何分组可一键回到蓝图中的归属位置。
 */
export default function BlueprintDemoAssetsPage() {
  const { id = DEMO_PROJECT_ID } = useParams();
  const query = useSearchParams();
  const scenarioKey = (query.get("sc") as ScenarioKey) || "drama";
  const scenario = useMemo(
    () => SCENARIOS.find((item) => item.key === scenarioKey) ?? SCENARIOS[0],
    [scenarioKey],
  );
  const episodes = useMemo(() => episodesOf(scenario), [scenario]);
  const [detail, setDetailState] = useState<DetailData | null>(null);
  const [scriptEpisode, setScriptEpisodeState] = useState<EpisodeScript | null>(
    null,
  );
  const setDetail = (value: DetailData | null) => {
    setDetailState(value);
    if (value)
      useCreatorInteractionStore.getState().select(`blueprint:${value.title}`);
  };
  const setScriptEpisode = (value: EpisodeScript | null) => {
    setScriptEpisodeState(value);
    if (value)
      useCreatorInteractionStore.getState().select(`node:${value.name}`);
  };

  useEffect(() => {
    useProjectSnapshotStore.setState({
      projectId: id,
      project: buildDemoProject(scenario),
      generation: 1,
      etag: `demo-${scenario.key}`,
      syncStatus: "healthy",
    });
  }, [id, scenario]);

  const toBlueprint = () => navigate(`/blueprint-demo?sc=${scenario.key}`);
  interface ProducedItem {
    label: string;
    sub: string;
    tone: "done" | "run";
    grad: string;
  }
  const producedItems: ProducedItem[] = episodes.flatMap(
    (ep): ProducedItem[] => {
      if (ep.status.tone === "done")
        return [
          {
            label: `${ep.name} · 成片`,
            sub: ep.planMeta[0] ?? "",
            tone: "done",
            grad: ep.cast[0]?.grad ?? "g1",
          },
        ];
      if (ep.status.tone === "run")
        return [
          {
            label: `${ep.name} · 镜头片段`,
            sub: ep.status.text,
            tone: "run",
            grad: ep.cast[0]?.grad ?? "g1",
          },
        ];
      return [];
    },
  );

  const GroupHeader = ({
    icon,
    title,
    hint,
  }: {
    icon: React.ReactNode;
    title: string;
    hint: string;
  }) => (
    <div className="mb-2.5 flex items-center gap-2">
      <span className="text-[var(--color-accent)]">{icon}</span>
      <b className="text-[13px] font-semibold text-[var(--color-text-primary)]">
        {title}
      </b>
      <span className="min-w-0 truncate text-[11px] text-[var(--color-text-tertiary)]">
        {hint}
      </span>
      <button
        type="button"
        onClick={toBlueprint}
        className="ml-auto inline-flex shrink-0 items-center gap-0.5 text-[11px] font-semibold text-[var(--color-accent)] hover:underline"
      >
        在蓝图中查看归属
        <ArrowUpRight className="h-3 w-3" />
      </button>
    </div>
  );

  return (
    <div
      data-project-shell
      className="app-shell grid h-screen grid-rows-[58px_minmax(0,1fr)]"
    >
      <DemoTopNav
        navName={scenario.navName}
        navPreview={scenario.navPreview}
        active="assets"
        scenarioKey={scenario.key}
      />
      <div className="flex min-h-0 overflow-hidden">
        <main className="panel-enter relative min-h-0 min-w-0 flex-1 overflow-hidden bg-[var(--color-bg-layout)]">
          <div className="h-full overflow-y-auto px-6 py-5">
            <div className="mx-auto flex max-w-5xl flex-col gap-6">
              <section>
                <GroupHeader
                  icon={<FileText className="h-4 w-4" />}
                  title="剧本"
                  hint="每个叙事节点一份 timeline_script（体裁随场景：场次体 / 口播体 / 剪辑体），版本与审阅走通用 artifact 机制"
                />
                <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-3">
                  {episodes.map((ep) => (
                    <button
                      key={ep.id}
                      type="button"
                      onClick={() => setScriptEpisode(ep)}
                      className="surface surface-hover p-3 text-left"
                    >
                      <b className="block truncate text-xs font-semibold text-[var(--color-text-primary)]">
                        {ep.panelTitle ?? `剧本 · ${ep.name}`}
                      </b>
                      <span className="mt-1 flex items-center gap-1.5">
                        <span className="truncate text-[10px] text-[var(--color-text-tertiary)]">
                          {ep.version}
                        </span>
                        <span
                          className={`ml-auto shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                            TONE_CHIP[ep.status.tone]
                          }`}
                        >
                          {ep.status.text}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>

              {scenario.visual && (
                <section>
                  <GroupHeader
                    icon={<Palette className="h-4 w-4" />}
                    title="视觉开发"
                    hint="角色 / 场景设计资产 · 跨节点共享，一致性锚与版本链完整保留"
                  />
                  <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4 lg:grid-cols-6">
                    {scenario.visual.map((item) => (
                      <button
                        key={item.name}
                        type="button"
                        onClick={() => setDetail(item.detail)}
                        className={`overflow-hidden rounded-[10px] border bg-[var(--color-bg-card)] text-left transition-all hover:border-[var(--color-accent)] hover:shadow-[var(--shadow-sm)] ${
                          item.pending
                            ? "border-[rgba(247,144,9,.55)]"
                            : "border-[var(--color-border)]"
                        }`}
                      >
                        <span
                          className="relative flex h-[92px] items-end p-1.5 text-[10px] font-semibold text-white [text-shadow:0_1px_3px_rgba(0,0,0,.6)]"
                          style={{ backgroundImage: GRADS[item.grad] }}
                        >
                          {item.name.split(" · ")[0]}
                          <span className="absolute right-1.5 top-1.5 rounded bg-black/55 px-1.5 py-0.5 text-[9px] font-bold [text-shadow:none]">
                            {item.tag}
                          </span>
                        </span>
                        <span className="block px-2 py-1.5">
                          <span
                            className={`block truncate text-[10px] ${
                              TONE_TEXT[item.tone]
                            }`}
                          >
                            {item.state}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              <section>
                <GroupHeader
                  icon={<FolderSearch className="h-4 w-4" />}
                  title="调研与理解"
                  hint="素材理解索引 + browser-use 调研报告（research_report artifact），逐页可溯源"
                />
                <div className="surface overflow-hidden">
                  {scenario.research.map((item) => (
                    <button
                      key={item.title}
                      type="button"
                      onClick={() => setDetail(item.detail)}
                      className="flex w-full items-start gap-2.5 border-b border-[var(--color-border)] px-3.5 py-2.5 text-left transition-colors last:border-b-0 hover:bg-[var(--color-bg-secondary)]"
                    >
                      <span
                        className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg text-[13px]"
                        style={{ background: item.iconBg }}
                      >
                        {item.icon}
                      </span>
                      <span className="min-w-0 flex-1">
                        <b className="block truncate text-xs font-semibold text-[var(--color-text-primary)]">
                          {item.title}
                        </b>
                        <span className="mt-0.5 line-clamp-1 text-[11px] text-[var(--color-text-secondary)]">
                          {item.summary}
                        </span>
                      </span>
                      <span
                        className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                          TONE_CHIP[item.tone]
                        }`}
                      >
                        {item.tag}
                      </span>
                    </button>
                  ))}
                </div>
              </section>

              <section>
                <GroupHeader
                  icon={<Video className="h-4 w-4" />}
                  title="镜头与成片"
                  hint="生产产物按节点归属；点击节点剧本或蓝图节点可定位上下文"
                />
                {producedItems.length ? (
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
                    {producedItems.map((item) => (
                      <div
                        key={item.label}
                        className="overflow-hidden rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-card)]"
                      >
                        <span
                          className="block h-[64px]"
                          style={{ backgroundImage: GRADS[item.grad] }}
                        />
                        <span className="block px-2.5 py-2">
                          <b className="block truncate text-[11px] font-semibold text-[var(--color-text-primary)]">
                            {item.label}
                          </b>
                          <span
                            className={`text-[10px] ${TONE_TEXT[item.tone]}`}
                          >
                            {item.sub}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="surface px-4 py-6 text-center text-[11px] text-[var(--color-text-tertiary)]">
                    生产尚未开始 ——
                    通过蓝图中的剧本审阅后，镜头与成片会归档到这里
                  </p>
                )}
              </section>
            </div>
          </div>

          {/* 内嵌面板：只覆盖工作区，AgentDock 始终可见 */}
          <ScriptDrawer
            episode={scriptEpisode}
            open={scriptEpisode !== null}
            visualPool={scenario.visual}
            onClose={() => setScriptEpisodeState(null)}
            onOpenTimeline={(episode) =>
              navigate(
                `/blueprint-demo/${DEMO_PROJECT_ID}/plan?sc=${scenario.key}&ep=${episode.id}`,
              )
            }
            onOpenVisual={(item) => {
              setScriptEpisodeState(null);
              setDetail(item.detail);
            }}
          />
          {detail && (
            <div
              className="absolute inset-0 z-30 flex justify-end bg-[rgba(20,16,12,.18)]"
              onClick={() => setDetailState(null)}
            >
              <div
                className="panel-enter flex h-full w-[min(560px,92%)] flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-[-8px_0_28px_rgba(0,0,0,.08)]"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
                  <span className="text-sm font-semibold text-[var(--color-text-primary)]">
                    资产详情
                  </span>
                  <button
                    type="button"
                    onClick={() => setDetailState(null)}
                    className="icon-button !h-7 !w-7"
                    title="关闭（选中引用保留在创作助手中）"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-5 pt-3">
                  <DetailView
                    detail={detail}
                    onBack={() => setDetailState(null)}
                  />
                </div>
              </div>
            </div>
          )}
        </main>
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
