import { useMemo } from "react";
import { message } from "antd";
import { Check, LayoutList, MessageSquareText, X } from "lucide-react";
import type { EpisodeScript, ScriptBlock, VisualItem } from "./demoData";
import { GRADS, TONE_CHIP } from "./demoData";

function BlockView({ block }: { block: ScriptBlock }) {
  if (block.kind === "scene") {
    return (
      <span className="mb-1.5 mt-3.5 inline-block rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-0.5 text-[11px] font-bold tracking-wide text-[var(--color-text-secondary)] first:mt-0">
        {block.text}
      </span>
    );
  }
  if (block.kind === "action") {
    return (
      <p className="my-1 text-[var(--color-text-secondary)]">
        {block.text}
        {block.refs && (
          <span className="mt-1 flex flex-wrap gap-1.5">
            {block.refs.map((ref) => (
              <button
                key={ref}
                type="button"
                onClick={() => message.info(`（演示）回看片段：${ref}`)}
                className="inline-flex items-center rounded-md border border-[rgba(59,130,246,.35)] bg-[rgba(59,130,246,.08)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary,#3b82f6)] transition-colors hover:border-[var(--color-primary,#3b82f6)]"
              >
                {ref}
              </button>
            ))}
          </span>
        )}
      </p>
    );
  }
  if (block.kind === "line") {
    return (
      <p className="my-1 ml-8">
        <b className="mr-2 text-[var(--color-text-primary)]">
          {block.character}
        </b>
        {block.parenthetical && (
          <span className="mr-1.5 text-xs text-[var(--color-text-tertiary)]">
            （{block.parenthetical}）
          </span>
        )}
        {block.text}
      </p>
    );
  }
  return (
    <div className="mt-2.5 rounded-r-lg border-l-[3px] border-[var(--color-accent)] bg-[var(--color-accent-soft)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
      {block.text}
    </div>
  );
}

interface ScriptDrawerProps {
  episode: EpisodeScript | null;
  open: boolean;
  visualPool: VisualItem[] | null;
  onClose: () => void;
  onOpenTimeline: (episode: EpisodeScript) => void;
  onOpenVisual: (item: VisualItem) => void;
}

/**
 * Inline script review panel: overlays only the workspace column, so the
 * AgentDock stays visible/usable and the selected node remains referenced in
 * the assistant context. Approval itself lives in the dock DecisionTray —
 * this panel only offers editing actions.
 */
export default function ScriptDrawer({
  episode,
  open,
  visualPool,
  onClose,
  onOpenTimeline,
  onOpenVisual,
}: ScriptDrawerProps) {
  const [messageApi, contextHolder] = message.useMessage();
  const title = useMemo(() => {
    if (!episode) return "";
    return episode.panelTitle ?? `剧本 · ${episode.name.replace(" · ", " ")}`;
  }, [episode]);

  if (!open || !episode) return null;

  return (
    <div className="panel-enter absolute inset-0 z-30 flex min-h-0 flex-col bg-[var(--color-bg-layout)]">
      {contextHolder}
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-5 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="icon-button !h-8 !w-8 shrink-0"
            title="关闭（选中引用保留在创作助手中）"
          >
            <X className="h-4 w-4" />
          </button>
          <MessageSquareText className="h-4 w-4 shrink-0 text-[var(--color-accent)]" />
          <h3 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
            {title}
          </h3>
          <span className="shrink-0 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 py-0.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
            {episode.version}
          </span>
          <span
            className={`shrink-0 rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
              TONE_CHIP[episode.status.tone]
            }`}
          >
            {episode.status.text}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {episode.status.tone === "wait" && (
            <span className="inline-flex items-center gap-1 text-[11px] text-[var(--color-text-tertiary)]">
              <Check className="h-3 w-3" />
              审阅通过 / 驳回在右侧创作助手的待决策卡中完成
            </span>
          )}
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              messageApi.success("已把本稿与你的批注发给创作助手重写")
            }
          >
            提出修改
          </button>
          <span className="mx-0.5 h-[22px] w-px bg-[var(--color-border)]" />
          <button
            type="button"
            onClick={() => onOpenTimeline(episode)}
            className="inline-flex items-center gap-2 rounded-[10px] bg-[var(--color-text-primary)] px-5 py-2.5 text-sm font-bold leading-none text-[var(--color-bg-primary)] shadow-[0_2px_8px_rgba(0,0,0,.2)] transition-all hover:-translate-y-px hover:opacity-90 hover:shadow-[0_4px_14px_rgba(0,0,0,.25)]"
          >
            <LayoutList className="h-4 w-4" />
            进入时间线编辑
          </button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,7fr)_minmax(0,3fr)]">
        <div
          data-creator-field={`node:${episode.id}/script`}
          data-creator-field-label={`剧本 · ${episode.name}`}
          className="min-h-0 overflow-y-auto border-r border-[var(--color-border)] bg-[var(--color-bg-primary)] px-6 py-5 text-[13px] leading-[1.9] text-[var(--color-text-primary)] outline-none focus:shadow-[inset_0_0_0_2px_var(--color-accent-soft)]"
          contentEditable
          suppressContentEditableWarning
          spellCheck={false}
        >
          {episode.blocks.map((block, index) => (
            <BlockView key={index} block={block} />
          ))}
        </div>
        <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto bg-[rgba(244,241,234,.45)] p-4">
          <div>
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
              本集梗概（可改，改动会级联标记下游为过期）
            </span>
            <div
              contentEditable
              suppressContentEditableWarning
              spellCheck={false}
              data-creator-field={`node:${episode.id}/synopsis`}
              data-creator-field-label={`${episode.name} · 梗概`}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-xs leading-relaxed text-[var(--color-text-secondary)] outline-none focus:border-[var(--color-accent)] focus:shadow-[0_0_0_2px_rgba(255,127,22,.1)]"
            >
              {episode.synopsis}
            </div>
          </div>
          <div>
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
              阶段状态
            </span>
            <div className="flex flex-wrap gap-1.5">
              {episode.stages.map((stage) => (
                <span
                  key={stage.label}
                  className={`rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                    TONE_CHIP[stage.tone]
                  }`}
                >
                  {stage.label}
                </span>
              ))}
            </div>
          </div>
          <div>
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
              登场角色 / 场景（点击查看视觉设计）
            </span>
            <div className="flex flex-wrap gap-1.5">
              {episode.cast.map((member) => (
                <button
                  key={member.label}
                  type="button"
                  title="打开视觉设计详情"
                  onClick={() => {
                    const hit = visualPool?.find((item) =>
                      item.name.includes(member.label),
                    );
                    if (hit) onOpenVisual(hit);
                    else
                      messageApi.info(
                        "该实体的视觉设计尚未开始（等待剧本通过）",
                      );
                  }}
                  className="flex h-11 w-11 items-end justify-center rounded-lg border border-[var(--color-border)] pb-0.5 text-[9px] text-white [text-shadow:0_1px_2px_rgba(0,0,0,.5)] transition-transform hover:-translate-y-px"
                  style={{ backgroundImage: GRADS[member.grad] }}
                >
                  {member.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
              规划
            </span>
            {episode.planMeta.map((line) => (
              <p
                key={line}
                className="text-xs leading-relaxed text-[var(--color-text-secondary)]"
              >
                {line}
              </p>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
