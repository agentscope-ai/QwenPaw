import { useEffect, useMemo, useRef } from "react";
import { Film, Layers3, Music2, Sparkles, WandSparkles } from "lucide-react";
import type {
  TaskView,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import {
  classifyElementTrack,
  elementCreationSummary,
  trackOrderedTimelineElements,
  resolveElementVisualMeta,
} from "@/selectors/timelineElementSelectors";
import { useAgentWorkingState } from "@/selectors/agentWorkingSelectors";

interface ElementListProps {
  timeline: TimelineDocument;
  playheadTick: number;
  activeElementIds: string[];
  selectedElementId: string | null;
  tasks: TaskView[];
  onSelect: (elementId: string) => void;
}

function TypeIcon({ element }: { element: TimelineElementDocument }) {
  const track = classifyElementTrack(element);
  if (element.creation.type === "audio" || track === null)
    return <Music2 className="h-3.5 w-3.5" />;
  if (track === "subtitle") return <Layers3 className="h-3.5 w-3.5" />;
  if (track === "motion") return <Sparkles className="h-3.5 w-3.5" />;
  if (track === "transition") return <WandSparkles className="h-3.5 w-3.5" />;
  if (track === "ai") return <Sparkles className="h-3.5 w-3.5" />;
  return <Film className="h-3.5 w-3.5" />;
}

function statusOf(
  element: TimelineElementDocument,
  tasks: TaskView[],
): { label: string; tone: string } {
  if (!element.enabled)
    return {
      label: "已停用",
      tone: "bg-[var(--color-bg-secondary)] text-[var(--color-text-tertiary)]",
    };
  const related = tasks.find(
    (task) => task.targetRef === `element:${element.element_id}`,
  );
  if (related?.status === "RUNNING" || related?.status === "QUEUED") {
    return {
      label: related.status === "RUNNING" ? "生成中" : "等待中",
      tone: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
    };
  }
  if (related?.status === "FAILED" || related?.status === "QUARANTINED") {
    return {
      label: "需处理",
      tone: "bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
    };
  }
  if (Object.keys(element.outputs).length > 0) {
    return {
      label: "已有产物",
      tone: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
    };
  }
  return {
    label: "可编辑",
    tone: "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]",
  };
}

function sec(tick: number, ticksPerSecond: number): string {
  return (tick / ticksPerSecond).toFixed(1).replace(/\.0$/, "");
}

export default function ElementList({
  timeline,
  playheadTick,
  activeElementIds,
  selectedElementId,
  tasks,
  onSelect,
}: ElementListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());
  const agentWorking = useAgentWorkingState();
  const elements = useMemo(
    () => trackOrderedTimelineElements(timeline),
    [timeline],
  );

  useEffect(() => {
    if (!selectedElementId) return;
    const item = itemRefs.current.get(selectedElementId);
    const list = listRef.current;
    if (!item || !list) return;
    const itemRect = item.getBoundingClientRect();
    const listRect = list.getBoundingClientRect();
    if (itemRect.top < listRect.top || itemRect.bottom > listRect.bottom) {
      const centeredDelta =
        itemRect.top - listRect.top - (listRect.height - itemRect.height) / 2;
      list.scrollTop = Math.max(0, list.scrollTop + centeredDelta);
    }
  }, [selectedElementId]);

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-sm">
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
        <div className="flex min-w-0 items-baseline gap-1.5">
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
            时间点:{sec(playheadTick, timeline.ticks_per_second)}s,{" "}
            {activeElementIds.length}项内容
          </h3>
          <span className="truncate text-[10px] text-[var(--color-text-tertiary)]">
            按开始时间排序
          </span>
        </div>
      </header>
      <div
        ref={listRef}
        data-element-list
        className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3 [scrollbar-gutter:stable]"
      >
        {elements.length === 0 ? (
          agentWorking.working ? (
            <div
              data-element-list-working
              className="flex h-full min-h-44 flex-col items-center justify-center px-6 text-center"
            >
              <div className="agent-working-breathe mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--color-accent-soft)]">
                <Sparkles className="h-6 w-6 text-[var(--color-accent)]" />
              </div>
              <p className="agent-working-dots text-sm font-semibold text-[var(--color-text-primary)]">
                Agent 正在规划视频方案
              </p>
              <span className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full bg-[var(--color-bg-secondary)] px-3 py-1 text-[11px] text-[var(--color-text-secondary)]">
                <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-warning)]" />
                <span className="truncate">
                  {agentWorking.hint || "正在分析你的创作需求"}
                </span>
              </span>
              <p className="mt-2 text-xs leading-5 text-[var(--color-text-tertiary)]">
                方案生成后，时间线内容会自动出现在这里。
              </p>
              <div className="agent-working-shimmer mt-4 h-1 w-40 rounded-full bg-[var(--color-bg-secondary)]" />
            </div>
          ) : (
            <div className="flex h-full min-h-44 flex-col items-center justify-center px-6 text-center">
              <Sparkles className="mb-3 h-7 w-7 text-[var(--color-accent)]" />
              <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                时间轴还是空的
              </p>
              <p className="mt-1 text-xs leading-5 text-[var(--color-text-tertiary)]">
                在 Agent 中描述想生成、剪辑和叠加的画面，方案会自动出现在这里。
              </p>
            </div>
          )
        ) : (
          elements
            .filter((element) => activeElementIds.includes(element.element_id))
            .map((element) => {
              const selected = selectedElementId === element.element_id;
              const active = activeElementIds.includes(element.element_id);
              const meta = resolveElementVisualMeta(element);
              const status = statusOf(element, tasks);
              const start = element.span.start_tick;
              const end = start + element.span.duration_tick;
              return (
                <button
                  key={element.element_id}
                  ref={(node) => {
                    if (node) itemRefs.current.set(element.element_id, node);
                    else itemRefs.current.delete(element.element_id);
                  }}
                  type="button"
                  data-element-list-item={element.element_id}
                  onClick={() => onSelect(element.element_id)}
                  className={`relative w-full overflow-hidden rounded-xl border p-3 text-left transition ${
                    selected
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]/45 shadow-sm ring-2 ring-[var(--color-accent)]/10"
                      : "border-[var(--color-border)] bg-white hover:border-[var(--color-border-strong)] hover:shadow-sm"
                  } ${element.enabled ? "" : "opacity-60"}`}
                >
                  <i
                    className="absolute inset-y-0 left-0 w-1"
                    style={{ background: meta.color }}
                  />
                  <div className="flex items-start justify-between gap-2 pl-1">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <span style={{ color: meta.color }}>
                          <TypeIcon element={element} />
                        </span>
                        <span className="truncate text-[13px] font-semibold text-[var(--color-text-primary)]">
                          {element.label || element.element_id}
                        </span>
                        {active && (
                          <span
                            className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-accent)]"
                            title="当前时刻活跃"
                          />
                        )}
                      </div>
                      <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-[var(--color-text-secondary)]">
                        {elementCreationSummary(element.creation) ||
                          "尚未补充创作说明"}
                      </p>
                    </div>
                    <div className="ml-auto flex shrink-0 items-center gap-1">
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold`}
                        style={{ color: meta.color, background: meta.soft }}
                      >
                        {meta.label}
                      </span>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold text-[var(--color-text-tertiary)]`}
                      >
                        {sec(start, timeline.ticks_per_second)}s –{" "}
                        {sec(end, timeline.ticks_per_second)}s
                      </span>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold ${status.tone}`}
                      >
                        {status.label}
                      </span>
                    </div>
                  </div>
                </button>
              );
            })
        )}
      </div>
    </section>
  );
}
