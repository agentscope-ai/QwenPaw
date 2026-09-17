import { useMemo } from "react";
import { Alert, Button, Input, InputNumber, Select } from "antd";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
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
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
} from "@/api/creator";
import {
  TRANSITION_KIND_LABEL,
  resolveElementOutputs,
  resolveElementVisualMeta,
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

function getTransitionKindOptions() {
  return [
    "crossfade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "wipeleft",
    "cut",
  ].map((kind) => ({
    value: kind,
    label: `${i18n.t(TRANSITION_KIND_LABEL[kind] ?? "")}（${kind}）`,
  }));
}

function getTransitionEasingOptions(t: (key: string) => string) {
  return [
    { value: "linear", label: t("elementDetail.easingOptions.linear") },
    { value: "ease-in", label: t("elementDetail.easingOptions.easeIn") },
    { value: "ease-out", label: t("elementDetail.easingOptions.easeOut") },
    { value: "ease-in-out", label: t("elementDetail.easingOptions.easeInOut") },
  ];
}

function taskStatus(
  element: TimelineElementDocument,
  tasks: TaskView[],
  t: (key: string) => string,
) {
  const task = tasks.find(
    (item) => item.targetRef === `element:${element.element_id}`,
  );
  if (task?.status === "RUNNING" || task?.status === "QUEUED")
    return {
      label:
        task.status === "RUNNING"
          ? t("elementDetail.generating")
          : t("elementDetail.waiting"),
      tone: "text-[var(--color-warning)] bg-[var(--color-warning-soft)]",
    };
  if (task?.status === "FAILED" || task?.status === "QUARANTINED")
    return {
      label: t("elementDetail.genFailed"),
      tone: "text-[var(--color-danger)] bg-[var(--color-danger-soft)]",
    };
  if (Object.keys(element.outputs).length)
    return {
      label: t("elementDetail.hasProduct"),
      tone: "text-[var(--color-success)] bg-[var(--color-success-soft)]",
    };
  return {
    label: t("elementDetail.editable"),
    tone: "text-[var(--color-text-secondary)] bg-[var(--color-bg-secondary)]",
  };
}

function sec(tick: number, ticksPerSecond: number): number {
  return Number((tick / ticksPerSecond).toFixed(3));
}

function getLocationFields(t: (key: string) => string) {
  return {
    x: t("elementDetail.xPosition"),
    y: t("elementDetail.yPosition"),
    width: t("elementDetail.width"),
    height: t("elementDetail.height"),
    rotation_degrees: t("elementDetail.rotation"),
    opacity: t("elementDetail.opacity"),
  } as const;
}

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
  const { t } = useTranslation();
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
            {t("elementDetail.selectElement")}
          </h3>
          <p className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
            {t("elementDetail.selectElementDesc")}
          </p>
        </div>
      </section>
    );
  }

  const meta = resolveElementVisualMeta(element);
  const status = taskStatus(element, tasks, t);
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
            {t("elementDetail.discardChanges")}
          </Button>
          <Button
            size="small"
            type="primary"
            loading={applying}
            disabled={dirtyCount === 0 || conflictPaths.length > 0}
            onClick={onApply}
            className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
          >
            {dirtyCount > 0
              ? t("elementDetail.applyChangesCount", { count: dirtyCount })
              : t("elementDetail.applyChanges")}
          </Button>
          {!element.enabled && (
            <span className="rounded-full bg-[var(--color-bg-secondary)] px-2 py-0.5 text-[10px] text-[var(--color-text-tertiary)]">
              {t("elementDetail.disabled")}
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
            aria-label={t("elementDetail.closeDetail")}
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
            message={t("elementDetail.conflictTitle")}
            description={
              <div className="space-y-2">
                <p>{t("elementDetail.conflictDesc")}</p>
                <Button size="small" onClick={onAcceptConflicts}>
                  {t("elementDetail.useMyChanges")}
                </Button>
              </div>
            }
          />
        )}
        <section className="rounded-xl border border-[var(--color-border)] p-3">
          <div className="mb-3">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
              <Clock3 className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              {t("elementDetail.timeAndLayer")}
            </h4>
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <label>
              <FieldLabel>{t("elementDetail.startTime")}</FieldLabel>
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
              <FieldLabel>{t("elementDetail.durationLabel")}</FieldLabel>
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
              <FieldLabel>{t("elementDetail.zIndex")}</FieldLabel>
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
              label={t("elementDetail.nameLabel")}
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
              {t("elementDetail.positionInFrame")}
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
                    <FieldLabel>{getLocationFields(t)[key]}</FieldLabel>
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
            {t("elementDetail.creationContent")}
          </h4>
          {creation.type === "r2v" && (
            <div className="space-y-3">
              <TextField
                label={t("elementDetail.intent")}
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
                label={t("elementDetail.narrative")}
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
                label={t("elementDetail.storyboardDesc")}
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
                label={t("elementDetail.videoDesc")}
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
                  <FieldLabel>{t("elementDetail.storyboards")}</FieldLabel>
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
                            {shot.camera || t("lib.camera")}
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
                label={t("elementDetail.editIntent")}
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
                label={t("elementDetail.reason")}
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
                      ]?.name || t("elementDetail.currentSource"),
                    )}
                  >
                    {decodeURIComponent(
                      project.assets.source_versions_by_id[
                        element.render_source.version_id
                      ]?.name || t("elementDetail.currentSource"),
                    )}
                  </b>
                  <br />
                  {t("elementDetail.using")}{" "}
                  {sec(
                    element.render_source.source_in_tick,
                    timeline.ticks_per_second,
                  )}
                  s –{" "}
                  {element.render_source.source_out_tick == null
                    ? t("elementDetail.end")
                    : `${sec(
                        element.render_source.source_out_tick,
                        timeline.ticks_per_second,
                      )}s`}
                  {" · "}
                  {element.render_source.playback_rate}{" "}
                  {t("elementDetail.speed")}
                </div>
              )}
            </div>
          )}
          {creation.type === "overlay" && (
            <div className="space-y-3">
              <TextField
                label={t("elementDetail.textLabel")}
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
                label={t("elementDetail.effectDesc")}
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
                  t("elementDetail.previousFrame")}{" "}
                →{" "}
                {timeline.elements_by_id[creation.to_element_id]?.label ||
                  t("elementDetail.nextFrame")}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label
                  data-creator-field={`element:${element.element_id}/creation/transition_kind`}
                  data-creator-path={pointer("creation", "transition_kind")}
                  className="block"
                >
                  <FieldLabel>{t("elementDetail.transitionType")}</FieldLabel>
                  <Select
                    className="w-full"
                    disabled={applying}
                    value={creation.transition_kind}
                    options={(() => {
                      const opts = getTransitionKindOptions();
                      return opts.some(
                        (option) => option.value === creation.transition_kind,
                      )
                        ? opts
                        : [
                            {
                              value: creation.transition_kind,
                              label: creation.transition_kind,
                            },
                            ...opts,
                          ];
                    })()}
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
                  <FieldLabel>{t("elementDetail.easing")}</FieldLabel>
                  <Select
                    className="w-full"
                    disabled={applying}
                    value={creation.easing}
                    options={
                      getTransitionEasingOptions(t).some(
                        (option) => option.value === creation.easing,
                      )
                        ? getTransitionEasingOptions(t)
                        : [
                            { value: creation.easing, label: creation.easing },
                            ...getTransitionEasingOptions(t),
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
                {t("elementDetail.transitionNote")}
              </p>
            </div>
          )}
          {creation.type === "audio" &&
            (() => {
              const audioVersion =
                project.assets.source_versions_by_id[
                  creation.source_asset_version_id
                ];
              const audioMeta = (audioVersion?.metadata ?? {}) as Record<
                string,
                unknown
              >;
              const textPreview = String(audioMeta.textPreview ?? "");
              const voiceName = String(audioMeta.voice ?? "");
              const ttsModel = String(audioMeta.model ?? "");
              // Streaming WAV headers can claim absurd durations (hours); hide
              // anything implausible instead of showing a broken number.
              const plausibleDuration =
                audioVersion?.duration_seconds != null &&
                audioVersion.duration_seconds > 0 &&
                audioVersion.duration_seconds < 4 * 3600
                  ? audioVersion.duration_seconds
                  : null;
              const spanSec = sec(
                element.span.duration_tick,
                timeline.ticks_per_second,
              );
              // Synthesized narration has no explicit duration knob on the
              // provider: length follows the script, so the editable script
              // shows its time budget and overruns are flagged here.
              const overBudget =
                plausibleDuration != null && plausibleDuration > spanSec + 0.05;
              const scriptText = creation.script || textPreview;
              // Only the CosyVoice family exposes a numeric speed knob;
              // qwen-tts length is controlled through the script alone.
              const supportsSpeechRate =
                ttsModel.startsWith("cosyvoice") ||
                ttsModel.includes("qwen-audio");
              return (
                <div className="space-y-3">
                  <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-secondary)]">
                    <div className="flex items-center justify-between gap-2">
                      <b className="text-[var(--color-text-primary)]">
                        {audioVersion?.name || "音频素材"}
                      </b>
                      <span
                        className={`text-[10px] ${
                          overBudget
                            ? "font-semibold text-[var(--color-warning)]"
                            : "text-[var(--color-text-tertiary)]"
                        }`}
                      >
                        {plausibleDuration != null
                          ? t("elementDetail.audioBudget", {
                              actual: plausibleDuration.toFixed(1),
                              budget: spanSec,
                            })
                          : "时长以试听为准"}
                      </span>
                    </div>
                    {overBudget && (
                      <p className="mt-1 text-[10px] text-[var(--color-warning)]">
                        {t("elementDetail.audioOverBudget")}
                      </p>
                    )}
                    {scriptText && (
                      <div
                        data-creator-field={`element:${element.element_id}/creation/script`}
                        data-creator-path={pointer("creation", "script")}
                        className="mt-1.5 space-y-1"
                      >
                        <Input.TextArea
                          value={scriptText}
                          autoSize={{ minRows: 2, maxRows: 6 }}
                          disabled={applying}
                          onChange={(event) =>
                            onChange((draft) => {
                              if (draft.creation.type === "audio")
                                draft.creation.script = event.target.value;
                            })
                          }
                          className="!text-xs"
                        />
                        <InlineReviewDiff
                          pointer={pointer("creation", "script")}
                        />
                        {supportsSpeechRate && (
                          <label
                            data-creator-field={`element:${element.element_id}/creation/speech_rate`}
                            data-creator-path={pointer(
                              "creation",
                              "speech_rate",
                            )}
                            className="flex items-center gap-2"
                          >
                            <span className="text-[10px] text-[var(--color-text-tertiary)]">
                              {t("elementDetail.speechRate")}
                            </span>
                            <InputNumber
                              size="small"
                              value={creation.speech_rate ?? 1.0}
                              min={0.5}
                              max={2}
                              step={0.1}
                              disabled={applying}
                              className="!w-20"
                              onChange={(value) =>
                                onChange((draft) => {
                                  if (draft.creation.type === "audio")
                                    draft.creation.speech_rate =
                                      typeof value === "number" ? value : 1.0;
                                })
                              }
                            />
                            <InlineReviewDiff
                              pointer={pointer("creation", "speech_rate")}
                            />
                          </label>
                        )}
                        <p className="text-[10px] text-[var(--color-text-tertiary)]">
                          {t("elementDetail.ttsScriptHint")}
                        </p>
                      </div>
                    )}
                    {(voiceName || ttsModel) && (
                      <p className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
                        {voiceName && `音色 ${voiceName}`}
                        {voiceName && ttsModel && " · "}
                        {ttsModel && `模型 ${ttsModel}`}
                      </p>
                    )}
                    {audioVersion && (
                      <audio
                        src={getAssetVersionMediaUrl(audioVersion.version_id)}
                        controls
                        preload="metadata"
                        className="mt-2 h-8 w-full"
                      />
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <label
                      data-creator-field={`element:${element.element_id}/creation/gain_db`}
                      data-creator-path={pointer("creation", "gain_db")}
                      className="block"
                    >
                      <FieldLabel>音量增益（dB）</FieldLabel>
                      <InputNumber
                        value={creation.gain_db}
                        step={1}
                        min={-30}
                        max={12}
                        disabled={applying}
                        className="w-full"
                        onChange={(value) =>
                          onChange((draft) => {
                            if (draft.creation.type === "audio")
                              draft.creation.gain_db = Number(value ?? 0);
                          })
                        }
                      />
                      <InlineReviewDiff
                        pointer={pointer("creation", "gain_db")}
                      />
                    </label>
                    <label
                      data-creator-field={`element:${element.element_id}/creation/pan`}
                      data-creator-path={pointer("creation", "pan")}
                      className="block"
                    >
                      <FieldLabel>声像（-1 左 – 1 右）</FieldLabel>
                      <InputNumber
                        value={creation.pan}
                        step={0.1}
                        min={-1}
                        max={1}
                        disabled={applying}
                        className="w-full"
                        onChange={(value) =>
                          onChange((draft) => {
                            if (draft.creation.type === "audio")
                              draft.creation.pan = Number(value ?? 0);
                          })
                        }
                      />
                      <InlineReviewDiff pointer={pointer("creation", "pan")} />
                    </label>
                  </div>
                  <p className="text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                    合成时该音频按 span
                    混入成片；旁白播放区间内会自动压低画面原声，避免互相干扰。
                  </p>
                </div>
              );
            })()}
        </section>

        {(creation.type === "r2v" ||
          creation.type === "t2v" ||
          creation.type === "i2v" ||
          creation.type === "s2v") && (
          <section className="rounded-xl border border-[var(--color-border)] p-3">
            <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
              <Film className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              {t("elementDetail.generationResult")}
            </h4>
            {outputs.length === 0 ? (
              <p className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-tertiary)]">
                {t("elementDetail.noResult")}
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
                          {output.selected
                            ? t("elementDetail.generated")
                            : t("elementDetail.notGenerated")}
                        </span>
                      </div>
                      {url && mediaType.startsWith("image/") && (
                        <img
                          src={url}
                          alt={`${output.name} ${t("lib.output")}`}
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
                          {t("elementDetail.resultStale")}
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

      {(creation.type === "r2v" ||
        creation.type === "t2v" ||
        creation.type === "i2v" ||
        creation.type === "s2v") && (
        <footer className="flex shrink-0 items-center justify-end border-t border-[var(--color-border)] bg-[var(--color-bg-primary)] px-4 py-3">
          <Button
            type="primary"
            icon={<ArrowUpRight className="h-3.5 w-3.5" />}
            disabled={dirtyCount > 0 || applying}
            onClick={() => onOpenWorkbench(element)}
          >
            {t("elementDetail.enterWorkbench", {
              mode: t(`r2v.modeLabel.${creation.type}`),
            })}
          </Button>
        </footer>
      )}
    </section>
  );
}
