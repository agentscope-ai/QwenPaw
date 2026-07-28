import { useMemo } from "react";
import { Alert, Button, Input, InputNumber, Select } from "antd";
import {
  ArrowUpRight,
  Box,
  Clock3,
  Film,
  Layers3,
  Sparkles,
  X,
} from "lucide-react";
import type {
  ProjectDocument,
  TaskView,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import {
  ELEMENT_TYPE_META,
  TRANSITION_KIND_LABEL,
  resolveElementOutputs,
} from "@/selectors/timelineElementSelectors";
import { outputLabel } from "@/lib/creatorPresentation";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";

interface ElementDetailProps {
  project: ProjectDocument;
  timeline: TimelineDocument;
  element: TimelineElementDocument | null;
  tasks: TaskView[];
  applying: boolean;
  dirtyCount: number;
  conflictPaths: string[];
  onClose: () => void;
  onChange: (mutator: (element: TimelineElementDocument) => void) => void;
  onApply: () => void;
  onDiscard: () => void;
  onAcceptConflicts: () => void;
  onOpenWorkbench: (element: TimelineElementDocument) => void;
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
      {children}
    </span>
  );
}

function TextField({
  label,
  value,
  multiline = false,
  path,
  field,
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  multiline?: boolean;
  path: string;
  field: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label
      data-creator-field={field}
      data-creator-path={path}
      data-creator-field-label={label}
      className="block"
    >
      <FieldLabel>{label}</FieldLabel>
      {multiline ? (
        <Input.TextArea
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          autoSize={{ minRows: 3, maxRows: 8 }}
        />
      ) : (
        <Input
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      <InlineReviewDiff pointer={path} />
    </label>
  );
}

const TRANSITION_KIND_OPTIONS = [
  "crossfade",
  "fadeblack",
  "fadewhite",
  "dissolve",
  "wipeleft",
  "cut",
].map((kind) => ({
  value: kind,
  label: `${TRANSITION_KIND_LABEL[kind]}（${kind}）`,
}));

const TRANSITION_EASING_OPTIONS = [
  { value: "linear", label: "匀速（linear）" },
  { value: "ease-in", label: "渐入（ease-in）" },
  { value: "ease-out", label: "渐出（ease-out）" },
  { value: "ease-in-out", label: "缓入缓出（ease-in-out）" },
];

function taskStatus(element: TimelineElementDocument, tasks: TaskView[]) {
  const task = tasks.find(
    (item) => item.targetRef === `element:${element.element_id}`,
  );
  if (task?.status === "RUNNING" || task?.status === "QUEUED")
    return {
      label: task.status === "RUNNING" ? "生成中" : "等待中",
      tone: "text-[var(--color-warning)] bg-[var(--color-warning-soft)]",
    };
  if (task?.status === "FAILED" || task?.status === "QUARANTINED")
    return {
      label: "生成失败",
      tone: "text-[var(--color-danger)] bg-[var(--color-danger-soft)]",
    };
  if (Object.keys(element.outputs).length)
    return {
      label: "已有产物",
      tone: "text-[var(--color-success)] bg-[var(--color-success-soft)]",
    };
  return {
    label: "可编辑",
    tone: "text-[var(--color-text-secondary)] bg-[var(--color-bg-secondary)]",
  };
}

function sec(tick: number, ticksPerSecond: number): number {
  return Number((tick / ticksPerSecond).toFixed(3));
}

const LOCATION_FIELDS = {
  x: "水平位置（%）",
  y: "垂直位置（%）",
  width: "画面宽度（%）",
  height: "画面高度（%）",
  rotation_degrees: "旋转角度（°）",
  opacity: "不透明度（%）",
} as const;

export default function ElementDetail({
  project,
  timeline,
  element,
  tasks,
  applying,
  dirtyCount,
  conflictPaths,
  onClose,
  onChange,
  onApply,
  onDiscard,
  onAcceptConflicts,
  onOpenWorkbench,
}: ElementDetailProps) {
  const outputs = useMemo(
    () => (element ? resolveElementOutputs(project, element) : []),
    [element, project],
  );

  if (!element) {
    return (
      <section
        data-onboarding-id="element-detail"
        className="flex min-h-0 items-center justify-center overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-sm"
      >
        <div className="max-w-sm px-8 text-center">
          <Layers3 className="mx-auto mb-3 h-8 w-8 text-[var(--color-text-tertiary)]" />
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
            选择一项时间线内容
          </h3>
          <p className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
            可从左侧列表或上方时间轴选择，查看其简介、创作方式、位置和产物。
          </p>
        </div>
      </section>
    );
  }

  const meta = ELEMENT_TYPE_META[element.creation.type];
  const status = taskStatus(element, tasks);
  const baseSegments = [
    "timelines",
    "items",
    timeline.timeline_id,
    "elements_by_id",
    element.element_id,
  ] as const;
  const pointer = (...segments: Array<string | number>) =>
    projectJsonPointer(...baseSegments, ...segments);
  const creation = element.creation;

  return (
    <section
      data-element-detail={element.element_id}
      data-onboarding-id="element-detail"
      className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-sm"
    >
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold"
              style={{ color: meta.color, background: meta.soft }}
            >
              {meta.label}
            </span>
            <h3 className="truncate text-base font-semibold text-[var(--color-text-primary)]">
              {element.label || element.element_id}
            </h3>
          </div>
        </div>
        <div
          data-element-detail-header-actions
          className="flex shrink-0 flex-wrap items-center justify-end gap-1.5"
        >
          <Button
            size="small"
            disabled={dirtyCount === 0 || applying}
            onClick={onDiscard}
            className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
          >
            放弃修改
          </Button>
          <Button
            size="small"
            type="primary"
            loading={applying}
            disabled={dirtyCount === 0 || conflictPaths.length > 0}
            onClick={onApply}
            className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
          >
            {dirtyCount > 0 ? `应用修改（${dirtyCount}）` : "应用修改"}
          </Button>
          {!element.enabled && (
            <span className="rounded-full bg-[var(--color-bg-secondary)] px-2 py-0.5 text-[10px] text-[var(--color-text-tertiary)]">
              已停用
            </span>
          )}
          <span
            data-element-detail-status
            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${status.tone}`}
          >
            {status.label}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="icon-button"
            aria-label="关闭内容详情"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 [scrollbar-gutter:stable]">
        {conflictPaths.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message="这些字段在编辑期间被其他操作更新"
            description={
              <div className="space-y-2">
                <p>
                  本地草稿仍然保留。确认使用本地修改覆盖最新值后，才能应用。
                </p>
                <Button size="small" onClick={onAcceptConflicts}>
                  使用我的修改
                </Button>
              </div>
            }
          />
        )}
        <section className="rounded-xl border border-[var(--color-border)] p-3">
          <div className="mb-3">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
              <Clock3 className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              时间与层级
            </h4>
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <label>
              <FieldLabel>开始时间（秒）</FieldLabel>
              <InputNumber
                className="w-full"
                min={0}
                step={0.1}
                disabled={applying}
                value={sec(element.span.start_tick, timeline.ticks_per_second)}
                onChange={(value) => {
                  if (value == null) return;
                  onChange((draft) => {
                    draft.span.start_tick = Math.round(
                      Number(value) * timeline.ticks_per_second,
                    );
                  });
                }}
              />
            </label>
            <label>
              <FieldLabel>持续时间（秒）</FieldLabel>
              <InputNumber
                className="w-full"
                min={1 / timeline.ticks_per_second}
                step={0.1}
                disabled={applying}
                value={sec(
                  element.span.duration_tick,
                  timeline.ticks_per_second,
                )}
                onChange={(value) => {
                  if (value == null) return;
                  onChange((draft) => {
                    draft.span.duration_tick = Math.max(
                      1,
                      Math.round(Number(value) * timeline.ticks_per_second),
                    );
                  });
                }}
              />
            </label>
            <label>
              <FieldLabel>叠放顺序</FieldLabel>
              <InputNumber
                className="w-full"
                disabled={applying}
                value={element.z_index}
                onChange={(value) =>
                  value != null &&
                  onChange((draft) => {
                    draft.z_index = Number(value);
                  })
                }
              />
            </label>
          </div>
          <div className="mt-3">
            <TextField
              label="名称"
              value={element.label}
              path={pointer("label")}
              field={`element:${element.element_id}/label`}
              disabled={applying}
              onChange={(value) =>
                onChange((draft) => {
                  draft.label = value;
                })
              }
            />
          </div>
        </section>

        {element.location && (
          <section className="rounded-xl border border-[var(--color-border)] p-3">
            <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
              <Box className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              成片画面位置
            </h4>
            <div className="grid gap-4 lg:grid-cols-[180px_minmax(0,1fr)]">
              <div className="flex min-h-40 items-center justify-center rounded-lg bg-[#191613] p-3">
                <div
                  className="relative max-h-36 w-full overflow-hidden rounded border border-white/15 bg-[#312b26]"
                  style={{
                    aspectRatio: project.settings.aspect_ratio.replace(
                      ":",
                      " / ",
                    ),
                  }}
                >
                  <div
                    data-element-location-box
                    className="absolute flex items-center justify-center overflow-hidden rounded border border-white/80 bg-[var(--color-accent)]/35 text-[9px] font-semibold text-white"
                    style={{
                      left: `${
                        (element.location.x -
                          element.location.width * element.location.anchor_x) *
                        100
                      }%`,
                      top: `${
                        (element.location.y -
                          element.location.height * element.location.anchor_y) *
                        100
                      }%`,
                      width: `${element.location.width * 100}%`,
                      height: `${element.location.height * 100}%`,
                      opacity: element.location.opacity,
                      transform: `rotate(${element.location.rotation_degrees}deg)`,
                      transformOrigin: `${element.location.anchor_x * 100}% ${
                        element.location.anchor_y * 100
                      }%`,
                    }}
                  >
                    {element.label || element.element_id}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {(
                  [
                    "x",
                    "y",
                    "width",
                    "height",
                    "rotation_degrees",
                    "opacity",
                  ] as const
                ).map((key) => (
                  <label key={key}>
                    <FieldLabel>{LOCATION_FIELDS[key]}</FieldLabel>
                    <InputNumber
                      className="w-full"
                      step={1}
                      disabled={applying}
                      min={
                        key === "width" || key === "height"
                          ? 0.1
                          : key === "opacity"
                          ? 0
                          : undefined
                      }
                      max={key === "opacity" ? 100 : undefined}
                      value={
                        key === "rotation_degrees"
                          ? element.location![key]
                          : Number((element.location![key] * 100).toFixed(1))
                      }
                      onChange={(value) => {
                        if (value == null) return;
                        const next =
                          key === "rotation_degrees"
                            ? Number(value)
                            : Number(value) / 100;
                        onChange((draft) => {
                          if (draft.location) draft.location[key] = next;
                        });
                      }}
                    />
                  </label>
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="rounded-xl border border-[var(--color-border)] p-3">
          <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
            <Sparkles className="h-3.5 w-3.5 text-[var(--color-accent)]" />
            创作内容
          </h4>
          {creation.type === "r2v" && (
            <div className="space-y-3">
              <TextField
                label="创作意图"
                value={creation.intent}
                multiline
                path={pointer("creation", "intent")}
                field={`element:${element.element_id}/creation/intent`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "r2v")
                      draft.creation.intent = value;
                  })
                }
              />
              <TextField
                label="叙事"
                value={creation.narrative}
                multiline
                path={pointer("creation", "narrative")}
                field={`element:${element.element_id}/creation/narrative`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "r2v")
                      draft.creation.narrative = value;
                  })
                }
              />
              <TextField
                label="分镜描述"
                value={creation.storyboard_prompt}
                multiline
                path={pointer("creation", "storyboard_prompt")}
                field={`element:${element.element_id}/creation/storyboard_prompt`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "r2v")
                      draft.creation.storyboard_prompt = value;
                  })
                }
              />
              <TextField
                label="画面生成描述"
                value={creation.video_prompt}
                multiline
                path={pointer("creation", "video_prompt")}
                field={`element:${element.element_id}/creation/video_prompt`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "r2v")
                      draft.creation.video_prompt = value;
                  })
                }
              />
              {creation.shots.order.length > 0 && (
                <div>
                  <FieldLabel>分镜</FieldLabel>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {creation.shots.order.map((shotId, index) => {
                      const shot = creation.shots.items[shotId];
                      if (!shot) return null;
                      return (
                        <div
                          key={shotId}
                          className="rounded-lg bg-[var(--color-bg-secondary)] p-2.5 text-[11px] leading-5 text-[var(--color-text-secondary)]"
                        >
                          <b className="text-[var(--color-text-primary)]">
                            {String(index + 1).padStart(2, "0")} ·{" "}
                            {shot.camera || "镜头"}
                          </b>
                          <p>{shot.description}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
          {creation.type === "edit" && (
            <div className="space-y-3">
              <TextField
                label="剪辑意图"
                value={creation.intent}
                multiline
                path={pointer("creation", "intent")}
                field={`element:${element.element_id}/creation/intent`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "edit")
                      draft.creation.intent = value;
                  })
                }
              />
              <TextField
                label="选择理由"
                value={creation.reason}
                multiline
                path={pointer("creation", "reason")}
                field={`element:${element.element_id}/creation/reason`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "edit")
                      draft.creation.reason = value;
                  })
                }
              />
              {element.render_source?.type === "source_asset_version" && (
                <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-[11px] leading-5 text-[var(--color-text-secondary)]">
                  <b
                    className="block truncate text-[var(--color-text-primary)]"
                    title={decodeURIComponent(
                      project.assets.source_versions_by_id[
                        element.render_source.version_id
                      ]?.name || "当前素材",
                    )}
                  >
                    {decodeURIComponent(
                      project.assets.source_versions_by_id[
                        element.render_source.version_id
                      ]?.name || "当前素材",
                    )}
                  </b>
                  <br />
                  选用{" "}
                  {sec(
                    element.render_source.source_in_tick,
                    timeline.ticks_per_second,
                  )}
                  s –{" "}
                  {element.render_source.source_out_tick == null
                    ? "结尾"
                    : `${sec(
                        element.render_source.source_out_tick,
                        timeline.ticks_per_second,
                      )}s`}
                  {" · "}
                  {element.render_source.playback_rate} 倍速
                </div>
              )}
            </div>
          )}
          {creation.type === "overlay" && (
            <div className="space-y-3">
              <TextField
                label="文本"
                value={creation.text}
                multiline
                path={pointer("creation", "text")}
                field={`element:${element.element_id}/creation/text`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "overlay")
                      draft.creation.text = value;
                  })
                }
              />
              <TextField
                label="动效描述"
                value={creation.prompt}
                multiline
                path={pointer("creation", "prompt")}
                field={`element:${element.element_id}/creation/prompt`}
                disabled={applying}
                onChange={(value) =>
                  onChange((draft) => {
                    if (draft.creation.type === "overlay")
                      draft.creation.prompt = value;
                  })
                }
              />
            </div>
          )}
          {creation.type === "transition" && (
            <div className="space-y-3">
              <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-secondary)]">
                {timeline.elements_by_id[creation.from_element_id]?.label ||
                  "前一画面"}{" "}
                →{" "}
                {timeline.elements_by_id[creation.to_element_id]?.label ||
                  "后一画面"}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label
                  data-creator-field={`element:${element.element_id}/creation/transition_kind`}
                  data-creator-path={pointer("creation", "transition_kind")}
                  className="block"
                >
                  <FieldLabel>转场类型</FieldLabel>
                  <Select
                    className="w-full"
                    disabled={applying}
                    value={creation.transition_kind}
                    options={
                      TRANSITION_KIND_OPTIONS.some(
                        (option) => option.value === creation.transition_kind,
                      )
                        ? TRANSITION_KIND_OPTIONS
                        : [
                            {
                              value: creation.transition_kind,
                              label: creation.transition_kind,
                            },
                            ...TRANSITION_KIND_OPTIONS,
                          ]
                    }
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "transition")
                          draft.creation.transition_kind = value;
                      })
                    }
                  />
                </label>
                <label
                  data-creator-field={`element:${element.element_id}/creation/easing`}
                  data-creator-path={pointer("creation", "easing")}
                  className="block"
                >
                  <FieldLabel>缓动</FieldLabel>
                  <Select
                    className="w-full"
                    disabled={applying}
                    value={creation.easing}
                    options={
                      TRANSITION_EASING_OPTIONS.some(
                        (option) => option.value === creation.easing,
                      )
                        ? TRANSITION_EASING_OPTIONS
                        : [
                            { value: creation.easing, label: creation.easing },
                            ...TRANSITION_EASING_OPTIONS,
                          ]
                    }
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "transition")
                          draft.creation.easing = value;
                      })
                    }
                  />
                </label>
              </div>
              <p className="text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                转场时长即上方“持续时间”，须落在两端画面的重叠区间内；
                预览统一以交叉溶解近似展示，成片按所选类型合成。
              </p>
            </div>
          )}
          {creation.type === "audio" && (
            <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-secondary)]">
              音频素材：
              {project.assets.source_versions_by_id[
                creation.source_asset_version_id
              ]?.name || "当前音频"}
              <br />
              音量 {creation.gain_db} dB · 声像 {creation.pan}
            </div>
          )}
        </section>

        {creation.type === "r2v" && (
          <section className="rounded-xl border border-[var(--color-border)] p-3">
            <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
              <Film className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              生成结果
            </h4>
            {outputs.length === 0 ? (
              <p className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-tertiary)]">
                当前还没有生成结果。
              </p>
            ) : (
              <div className="space-y-3">
                {outputs.map((output) => {
                  const file = output.selected
                    ? project.assets.files_by_id[output.selected.file_id]
                    : null;
                  const mediaType = file?.media_type || "";
                  const url = output.selected
                    ? getArtifactVersionMediaUrl(output.selected.version_id)
                    : null;
                  return (
                    <div
                      key={output.name}
                      className="overflow-hidden rounded-lg border border-[var(--color-border)]"
                    >
                      <div className="flex items-center justify-between gap-2 bg-[var(--color-bg-secondary)] px-3 py-2 text-[11px]">
                        <b>{outputLabel(output.name)}</b>
                        <span className="text-[var(--color-text-tertiary)]">
                          {output.selected ? "已生成" : "未生成"}
                        </span>
                      </div>
                      {url && mediaType.startsWith("image/") && (
                        <img
                          src={url}
                          alt={`${output.name} 输出`}
                          className="max-h-56 w-full bg-black object-contain"
                        />
                      )}
                      {url && mediaType.startsWith("video/") && (
                        <video
                          src={url}
                          controls
                          preload="metadata"
                          className="max-h-64 w-full bg-black object-contain"
                        />
                      )}
                      {url && mediaType.startsWith("audio/") && (
                        <audio src={url} controls className="w-full p-3" />
                      )}
                      {output.selected?.stale && (
                        <p className="px-3 py-2 text-[10px] text-[var(--color-warning)]">
                          该结果基于旧版方案，需要重新生成。
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}
      </div>

      {creation.type === "r2v" && (
        <footer className="flex shrink-0 items-center justify-end border-t border-[var(--color-border)] bg-[var(--color-bg-primary)] px-4 py-3">
          <Button
            type="primary"
            icon={<ArrowUpRight className="h-3.5 w-3.5" />}
            disabled={dirtyCount > 0 || applying}
            onClick={() => onOpenWorkbench(element)}
          >
            进入 R2V 工作台
          </Button>
        </footer>
      )}
    </section>
  );
}
