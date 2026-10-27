import { GitBranch, ListVideo, Plus } from "lucide-react";
import type {
  DetailData,
  EpisodeScript,
  ScenarioData,
  StripItem,
  Tone,
} from "./demoData";
import { TONE_CHIP, TONE_TEXT } from "./demoData";

const NODE_WIDTH = 218;

interface StructureAreaProps {
  scenario: ScenarioData;
  selectedId: string;
  onSelect: (episode: EpisodeScript) => void;
  onOpenTimeline: (episode: EpisodeScript) => void;
  onOpenDetail: (detail: DetailData) => void;
}

function StageChips({ stages }: { stages: { label: string; tone: Tone }[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {stages.map((stage) => (
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
  );
}

function TimelineQuickButton({ onClick }: { onClick: () => void }) {
  return (
    <span
      role="button"
      tabIndex={0}
      title="打开本集时间线"
      className="ml-2 inline-flex items-center gap-0.5 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-text-secondary)] opacity-0 transition-all group-hover:opacity-100 hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.stopPropagation();
          onClick();
        }
      }}
    >
      时间线 »
    </span>
  );
}

function GraphStructure({
  scenario,
  selectedId,
  onSelect,
  onOpenTimeline,
  onOpenDetail,
}: StructureAreaProps) {
  const graph = scenario.graph!;
  return (
    <div
      className="h-full overflow-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-[var(--shadow-xs)]"
      style={{
        backgroundImage:
          "radial-gradient(circle, #eee6da 1px, transparent 1px)",
        backgroundSize: "22px 22px",
      }}
    >
      <div
        className="relative"
        style={{ width: graph.width, height: graph.height }}
      >
        <svg className="pointer-events-none absolute inset-0 h-full w-full">
          {graph.edges.map((edge) => (
            <path
              key={edge.d}
              d={edge.d}
              fill="none"
              stroke={
                edge.active
                  ? "var(--color-accent)"
                  : "var(--color-border-strong)"
              }
              strokeWidth={edge.active ? 2 : 1.5}
            />
          ))}
        </svg>
        {graph.labels.map((label) => (
          <span
            key={label.text}
            className="absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-primary)] px-2.5 py-1 text-[10px] font-semibold text-[var(--color-text-secondary)] shadow-[var(--shadow-xs)]"
            style={{ left: label.x, top: label.y }}
          >
            {label.text}
          </span>
        ))}
        {graph.choice && (
          <button
            type="button"
            onClick={() => onOpenDetail(graph.choice!.detail)}
            className="absolute w-[158px] rounded-[14px] border-[1.5px] border-dashed border-[var(--color-accent)] bg-[var(--color-bg-card)] px-3 py-2.5 text-center shadow-[var(--shadow-xs)] transition-all hover:-translate-y-px hover:shadow-[var(--shadow-md)]"
            style={{ left: graph.choice.x, top: graph.choice.y }}
            title="点击查看/编辑抉择交互动效"
          >
            <span className="mb-1.5 inline-flex items-center gap-1 rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 text-[10px] font-bold text-[var(--color-accent)]">
              <GitBranch className="h-2.5 w-2.5" />
              观众抉择
            </span>
            <p className="text-[11px] font-medium leading-[1.45] text-[var(--color-text-primary)]">
              {graph.choice.question}
            </p>
            <span
              className={`mt-1.5 inline-block rounded px-1.5 text-[9px] font-semibold leading-[16px] ${
                TONE_CHIP[graph.choice.tone]
              }`}
            >
              {graph.choice.state}
            </span>
          </button>
        )}
        {graph.nodes.map((node) => {
          const selected = node.ep.id === selectedId;
          return (
            <button
              key={node.ep.id}
              type="button"
              onClick={() => onSelect(node.ep)}
              className={`group absolute rounded-xl border bg-[var(--color-bg-card)] p-3 text-left shadow-[var(--shadow-xs)] transition-all hover:-translate-y-px hover:border-[var(--color-accent)] hover:shadow-[var(--shadow-md)] ${
                selected
                  ? "border-[var(--color-accent)] shadow-[0_0_0_3px_var(--color-accent-soft)]"
                  : node.reviewing
                  ? "border-[var(--color-warning)] shadow-[0_0_0_3px_var(--color-warning-soft)]"
                  : "border-[var(--color-border)]"
              }`}
              style={{ left: node.x, top: node.y, width: NODE_WIDTH }}
            >
              <div className="mb-1.5 flex items-center justify-between gap-1.5">
                <span
                  className={`badge font-bold ${
                    node.ending
                      ? "bg-[rgba(139,92,246,.12)] text-[#8b5cf6]"
                      : "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  }`}
                >
                  {node.badge}
                </span>
                <span
                  className={`text-xs ${node.iconClass} ${
                    node.spin ? "animate-spin" : ""
                  }`}
                  title={node.ep.status.text}
                >
                  {node.icon}
                </span>
              </div>
              <h4 className="mb-1 text-[13px] font-semibold text-[var(--color-text-primary)]">
                {node.ep.name.split(" · ")[1] ?? node.ep.name}
              </h4>
              <p className="mb-2 line-clamp-2 text-[11px] leading-normal text-[var(--color-text-secondary)]">
                {node.ep.synopsis}
              </p>
              <div className="flex items-center justify-between border-t border-dashed border-[var(--color-border)] pt-2">
                <StageChips stages={node.ep.stages.slice(0, 3)} />
                <span className="flex shrink-0 items-center text-[10px] text-[var(--color-text-tertiary)]">
                  {node.meta}
                  <TimelineQuickButton
                    onClick={() => onOpenTimeline(node.ep)}
                  />
                </span>
              </div>
              {node.ep.status.progress != null && (
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
                  <div
                    className="h-full rounded-full bg-[var(--color-primary,#3b82f6)] transition-[width] duration-500"
                    style={{ width: `${node.ep.status.progress}%` }}
                  />
                </div>
              )}
            </button>
          );
        })}
        <button
          type="button"
          className="absolute inline-flex items-center gap-1 rounded-lg border border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-primary)]/70 px-2.5 py-1.5 text-[11px] text-[var(--color-text-tertiary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
          style={{ left: 960, top: 372 }}
        >
          <Plus className="h-3 w-3" />
          添加分支
        </button>
      </div>
    </div>
  );
}

function ListStructure({
  scenario,
  selectedId,
  onSelect,
  onOpenTimeline,
}: StructureAreaProps) {
  return (
    <div className="surface flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-2.5">
        <span className="flex items-center gap-2 text-xs font-semibold text-[var(--color-text-primary)]">
          <ListVideo className="h-3.5 w-3.5 text-[var(--color-accent)]" />
          剧集列表 · 线性 {scenario.episodes!.length} 集
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            className="btn-secondary !px-2.5 !py-1.5 !text-[11px]"
          >
            调整分集
          </button>
          <button
            type="button"
            className="btn-secondary !px-2.5 !py-1.5 !text-[11px]"
          >
            批量生成已通过剧集
          </button>
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {scenario.episodes!.map((item) => {
          const selected = item.ep.id === selectedId;
          return (
            <button
              key={item.ep.id}
              type="button"
              onClick={() => onSelect(item.ep)}
              className={`group flex w-full items-center gap-3.5 border-b border-[var(--color-border)] px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-[var(--color-bg-secondary)] ${
                selected
                  ? "bg-[var(--color-accent-soft)] shadow-[inset_3px_0_0_var(--color-accent)]"
                  : ""
              }`}
            >
              <span className="flex h-10 w-10 shrink-0 flex-col items-center justify-center rounded-[10px] bg-[var(--color-bg-secondary)] text-[15px] font-bold leading-none text-[var(--color-text-primary)]">
                <small className="mb-0.5 text-[9px] font-semibold text-[var(--color-text-tertiary)]">
                  EP
                </small>
                {item.n}
              </span>
              <span className="min-w-0 flex-1">
                <b className="block text-[13px] font-semibold text-[var(--color-text-primary)]">
                  {item.title}
                </b>
                <p className="mt-0.5 truncate text-[11px] text-[var(--color-text-secondary)]">
                  {item.ep.synopsis}
                </p>
              </span>
              <span className="flex shrink-0 items-center gap-3.5">
                <span
                  className={`rounded px-1.5 text-[10px] font-semibold leading-[18px] ${
                    TONE_CHIP[item.ep.status.tone]
                  }`}
                >
                  {item.ep.status.text}
                </span>
                <span className="w-[52px] text-right text-[11px] tabular-nums text-[var(--color-text-tertiary)]">
                  {item.dur}
                </span>
                <span
                  className={`w-4 text-center text-[13px] ${item.iconClass} ${
                    item.spin ? "animate-spin" : ""
                  }`}
                >
                  {item.icon}
                </span>
                <TimelineQuickButton onClick={() => onOpenTimeline(item.ep)} />
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function BoardItem({
  item,
  scenario,
  onSelect,
  onOpenDetail,
}: {
  item: StripItem;
  scenario: ScenarioData;
  onSelect: (episode: EpisodeScript) => void;
  onOpenDetail: (detail: DetailData) => void;
}) {
  const clickable = Boolean(item.ref);
  const handleClick = () => {
    if (!item.ref) return;
    if (item.ref.kind === "script") {
      onSelect(scenario.single!);
      return;
    }
    if (item.ref.kind === "visual") {
      const name = item.ref.name;
      const hit = scenario.visual?.find((entry) => entry.name === name);
      if (hit) onOpenDetail(hit.detail);
      return;
    }
    const title = item.ref.title;
    const hit = scenario.research.find((entry) => entry.title === title);
    if (hit) onOpenDetail(hit.detail);
  };
  const isScript = item.ref?.kind === "script";
  return (
    <button
      type="button"
      disabled={!clickable}
      onClick={handleClick}
      className={`w-full rounded-lg border px-2.5 py-2 text-left transition-all ${
        isScript
          ? "border-[var(--color-warning)] bg-[var(--color-warning-soft)] shadow-[0_0_0_3px_rgba(247,144,9,.08)] hover:-translate-y-px hover:shadow-[var(--shadow-sm)]"
          : clickable
          ? "border-[var(--color-border)] bg-[var(--color-bg-card)] hover:border-[var(--color-accent)] hover:shadow-[var(--shadow-sm)]"
          : "cursor-default border-dashed border-[var(--color-border)] bg-[var(--color-bg-primary)]/60"
      }`}
    >
      <span className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            item.tone === "done"
              ? "bg-[var(--color-success)]"
              : item.tone === "run"
              ? "bg-[var(--color-primary,#3b82f6)]"
              : item.tone === "wait"
              ? "animate-pulse bg-[var(--color-warning)]"
              : "bg-[var(--color-border-strong)]"
          }`}
        />
        <b className="min-w-0 flex-1 truncate text-[11px] font-semibold text-[var(--color-text-primary)]">
          {item.label}
        </b>
      </span>
      {item.sub && (
        <span
          className={`mt-0.5 block pl-3 text-[10px] leading-relaxed ${
            isScript
              ? "font-semibold text-[var(--color-warning)]"
              : "text-[var(--color-text-tertiary)]"
          }`}
        >
          {item.sub}
        </span>
      )}
    </button>
  );
}

function SingleStructure({
  scenario,
  onSelect,
  onOpenDetail,
}: StructureAreaProps) {
  return (
    <div className="flex h-full flex-col">
      <div className="grid min-h-0 flex-1 grid-cols-5 gap-3">
        {scenario.strip!.map((step, index) => (
          <div
            key={step.name}
            className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50"
          >
            <div className="flex items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2.5">
              <span
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-[1.5px] text-xs ${
                  step.tone === "done"
                    ? "border-[var(--color-success)] bg-[var(--color-success-soft)] text-[var(--color-success)]"
                    : step.tone === "wait"
                    ? "border-[var(--color-warning)] bg-[var(--color-warning-soft)] text-[var(--color-warning)] shadow-[0_0_0_4px_rgba(247,144,9,.08)]"
                    : step.tone === "run"
                    ? "border-[var(--color-primary,#3b82f6)] bg-[rgba(59,130,246,.08)] text-[var(--color-primary,#3b82f6)]"
                    : "border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-tertiary)]"
                }`}
              >
                {step.icon}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-[var(--color-text-primary)]">
                  {index + 1}. {step.name}
                </span>
                <span
                  className={`block truncate text-[10px] ${
                    TONE_TEXT[step.tone]
                  }`}
                >
                  {step.sub}
                </span>
              </span>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto p-2">
              {step.items.map((item) => (
                <BoardItem
                  key={item.label}
                  item={item}
                  scenario={scenario}
                  onSelect={onSelect}
                  onOpenDetail={onOpenDetail}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="pt-2.5 text-center text-[11px] text-[var(--color-text-tertiary)]">
        {scenario.singleHint}
      </p>
    </div>
  );
}

export default function StructureArea(props: StructureAreaProps) {
  if (props.scenario.structure === "graph")
    return <GraphStructure {...props} />;
  if (props.scenario.structure === "list") return <ListStructure {...props} />;
  return <SingleStructure {...props} />;
}
