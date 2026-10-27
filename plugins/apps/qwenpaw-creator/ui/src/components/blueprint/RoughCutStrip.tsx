import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Clapperboard, Play } from "lucide-react";
import { message } from "antd";
import type { EpisodeScript, ScenarioData, Tone } from "./demoData";
import { GRADS } from "./demoData";

interface RoughFrame {
  key: string;
  grad: string;
  label: string;
  kindLabel: string;
  tone: Tone;
  ep: EpisodeScript;
}

export function episodesOf(scenario: ScenarioData): EpisodeScript[] {
  if (scenario.structure === "graph")
    return scenario.graph!.nodes.map((node) => node.ep);
  if (scenario.structure === "list")
    return scenario.episodes!.map((item) => item.ep);
  return [scenario.single!];
}

/**
 * Rough-cut preview derived purely from EXISTING structures — no dedicated
 * data model. One frame per element/shot, sourced by priority:
 * selected element_video frame ▸ r2v_storyboard_image（每个生成 element 的
 * 必经产物，天然全覆盖）▸ visual_asset_image. In the demo, scene blocks of
 * each script stand in for the element list.
 */
function deriveFrames(scenario: ScenarioData): RoughFrame[] {
  const episodes = episodesOf(scenario);
  return episodes.flatMap((ep) => {
    const kindLabel =
      ep.status.tone === "done"
        ? "成片帧"
        : ep.status.tone === "run"
        ? "分镜/生成中"
        : ep.status.tone === "wait"
        ? "分镜草稿"
        : "待分镜";
    const scenes = ep.blocks
      .filter((block) => block.kind === "scene")
      .map((block) => {
        const parts = block.text.split(" · ");
        return parts.length >= 3 ? `${parts[0]}·${parts[2]}` : parts[0];
      });
    const list = scenes.length ? scenes : [ep.name.split(" · ")[0]];
    return list.map((scene, index) => ({
      key: `${ep.id}-${index}`,
      grad: ep.cast[index % ep.cast.length]?.grad ?? "g1",
      label: scene,
      kindLabel,
      tone: ep.status.tone,
      ep,
    }));
  });
}

const KIND_STYLE: Record<Tone, string> = {
  done: "bg-[var(--color-success)]/90",
  run: "bg-[var(--color-primary,#3b82f6)]/90",
  wait: "bg-[var(--color-warning)]/90",
  idle: "bg-black/50",
};

export default function RoughCutStrip({
  scenario,
  onSelect,
}: {
  scenario: ScenarioData;
  onSelect: (episode: EpisodeScript) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const frames = useMemo(() => deriveFrames(scenario), [scenario]);
  const readyCount = frames.filter((frame) => frame.tone === "done").length;

  return (
    <section className="shrink-0 border-t border-[var(--color-border)] bg-[var(--color-bg-primary)]/70 px-5 py-2 backdrop-blur">
      <div className="flex items-center gap-2.5">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
          <Clapperboard className="h-3.5 w-3.5 text-[var(--color-accent)]" />
          粗剪预览
        </span>
        <span className="min-w-0 truncate text-[11px] text-[var(--color-text-tertiary)]">
          全部镜头的分镜图按时间序排列（有成片帧则替换为成片帧）· 零额外生成成本
          · 成片帧 {readyCount}/{frames.length}
        </span>
        <button
          type="button"
          onClick={() =>
            message.info(
              "（演示）低清粗剪 = 现有产物按 timelines 顺序 ffmpeg 拼接，产物即普通 timeline_render artifact（draft 标记走 metadata）",
            )
          }
          className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-[11px] font-bold text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
        >
          <Play className="h-3 w-3" />
          播放粗剪
        </button>
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="icon-button !h-7 !w-7 shrink-0"
          title={collapsed ? "展开预览带" : "收起预览带"}
        >
          {collapsed ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      {!collapsed && (
        <div className="mt-2 flex items-stretch gap-1.5 overflow-x-auto pb-1">
          {frames.map((frame, index) => {
            const isEpisodeStart =
              index === 0 || frames[index - 1].ep.id !== frame.ep.id;
            return (
              <span key={frame.key} className="contents">
                {isEpisodeStart &&
                  frames.some((f) => f.ep.id !== frame.ep.id) && (
                    <span
                      className="flex w-[18px] shrink-0 items-center justify-center self-stretch rounded-sm bg-[var(--color-bg-secondary)] text-[9px] font-bold tracking-widest text-[var(--color-text-tertiary)] [writing-mode:vertical-rl]"
                      title={frame.ep.name}
                    >
                      {frame.ep.name.split(" · ")[0]}
                    </span>
                  )}
                <button
                  type="button"
                  title={`${frame.ep.name} · ${frame.kindLabel}（点击审阅该节点）`}
                  onClick={() => onSelect(frame.ep)}
                  className="group relative h-[88px] w-[52px] shrink-0 overflow-hidden rounded-md border border-[var(--color-border)] transition-all hover:-translate-y-0.5 hover:border-[var(--color-accent)] hover:shadow-[var(--shadow-sm)]"
                  style={{ backgroundImage: GRADS[frame.grad] }}
                >
                  <span
                    className={`absolute left-0 top-0 rounded-br px-1 py-px text-[8px] font-bold text-white ${
                      KIND_STYLE[frame.tone]
                    }`}
                  >
                    {frame.kindLabel}
                  </span>
                  <span className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 to-transparent px-1 pb-0.5 pt-2 text-left text-[8px] font-semibold text-white">
                    {frame.label}
                  </span>
                </button>
              </span>
            );
          })}
        </div>
      )}
    </section>
  );
}
