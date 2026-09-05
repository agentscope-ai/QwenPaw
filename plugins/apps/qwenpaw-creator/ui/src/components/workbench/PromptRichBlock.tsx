import { useEffect, useRef, useState } from "react";
import { Image, Input } from "antd";
import { Loader2, SquarePen, Wand2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";
import PromptEditorModal from "@/components/workbench/PromptEditorModal";
import type { ShotDocument } from "@/contracts/creator";

const { TextArea } = Input;

/** Design 84:39563: h40 full-round pill, ink fill, white 14px/500 text,
    20px magic-wand icon at gap 4, 16px horizontal padding. */
export function RegeneratePill({
  field,
  label,
  loading = false,
  disabled = false,
  onClick,
}: {
  field: string;
  label: string;
  loading?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-prompt-regenerate={field}
      disabled={disabled || loading}
      onClick={onClick}
      className="inline-flex h-10 shrink-0 cursor-pointer select-none items-center gap-1 rounded-full bg-[var(--color-text-primary)] px-4 text-sm font-medium leading-6 text-[var(--color-bg-primary)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {loading ? (
        <Loader2 className="h-5 w-5 animate-spin" />
      ) : (
        <Wand2 className="h-5 w-5" />
      )}
      {label}
    </button>
  );
}

export interface PromptRichToken {
  /** Authoritative [Image N] index this token answers to. */
  index: number;
  name: string;
  thumbUrl: string | null;
  kind: "storyboard" | "artifact" | "source" | "entity";
}

interface PromptSegment {
  /** null = unmarked prompt (single block); 0 = overview; N = 【Shot N】 */
  shotNumber: number | null;
  text: string;
}

const SHOT_HL_CLASS = "workbench-shot-hl";

/** 【Shot N】 is a text convention, not schema; prompts without it degrade to one block. */
function splitSegments(value: string): {
  marked: boolean;
  segments: PromptSegment[];
} {
  const parts = value.split(/【Shot (\d+)】/);
  if (parts.length === 1) {
    return { marked: false, segments: [{ shotNumber: null, text: value }] };
  }
  const segments: PromptSegment[] = [];
  const overview = parts[0].trim();
  if (overview) segments.push({ shotNumber: 0, text: overview });
  for (let i = 1; i < parts.length; i += 2) {
    segments.push({
      shotNumber: Number(parts[i]),
      text: (parts[i + 1] ?? "").trim(),
    });
  }
  return { marked: true, segments };
}

function shotRowElement(shotId: string): HTMLElement | null {
  const escaped =
    typeof CSS !== "undefined" && CSS.escape
      ? CSS.escape(shotId)
      : shotId.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  return document.querySelector<HTMLElement>(
    `[data-creator-module="shot-row"][data-creator-module-id="${escaped}"]`,
  );
}

/**
 * Prompt surface: the reference preview (with [Image N] citation tokens and
 * 【Shot N】 badges linked to the Shot list) is the only display mode; edits
 * go through the fullscreen editor opened from the 编辑 pill. A hidden
 * TextArea stays mounted so data-creator-* anchors, review focus and
 * controlled edits keep working.
 */
export default function PromptRichBlock({
  label,
  value,
  onChange,
  disabled = false,
  field,
  path,
  tokens,
  shots,
  collapseHeight = 230,
  placeholder,
  onRegenerate,
  regenerating = false,
  regenerateLabel,
  onEditComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  field: string;
  path: string;
  tokens: PromptRichToken[];
  shots?: ShotDocument[];
  collapseHeight?: number;
  placeholder?: string;
  /** Design contract: the prompt card foots with one explicit regenerate
      action (再次生成图片 / 再次生成视频) that persists the edited prompt and
      re-dispatches the generation. */
  onRegenerate?: () => void;
  regenerating?: boolean;
  regenerateLabel?: string;
  /** Fired after the fullscreen editor's 完成 writes back — the editor lives
      in a portal, so the host's blur-capture auto-save never sees it. */
  onEditComplete?: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const richRef = useRef<HTMLDivElement>(null);
  // 全屏编辑器（共享组件）：本地草稿，「完成」才写回。
  const [fullOpen, setFullOpen] = useState(false);

  const charCount = value.replace(/\s/g, "").length;
  const { marked, segments } = splitSegments(value);
  const shotSegmentCount = segments.filter(
    (segment) => (segment.shotNumber ?? 0) > 0,
  ).length;
  const segMismatch =
    marked && shots && shots.length > 0 && shotSegmentCount !== shots.length;
  const collapsed = overflowing && !expanded;

  // Measure after render (and when a hidden tab becomes visible) to decide
  // whether the collapse affordance is needed; hidden panes report 0 height.
  useEffect(() => {
    const element = richRef.current;
    if (!element) return;
    const check = () => {
      if (element.scrollHeight === 0) return;
      setOverflowing(element.scrollHeight > collapseHeight + 40);
    };
    check();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(check);
    observer.observe(element);
    return () => observer.disconnect();
  }, [value, collapseHeight]);

  const clearShotHighlight = () => {
    document
      .querySelectorAll(`.${SHOT_HL_CLASS}`)
      .forEach((el) => el.classList.remove(SHOT_HL_CLASS));
  };
  const shotOf = (shotNumber: number): ShotDocument | null =>
    shots?.[shotNumber - 1] ?? null;
  const highlightShot = (shotNumber: number) => {
    const shot = shotOf(shotNumber);
    if (shot) shotRowElement(shot.shot_id)?.classList.add(SHOT_HL_CLASS);
  };
  const scrollToShot = (shotNumber: number) => {
    const shot = shotOf(shotNumber);
    if (!shot) return;
    shotRowElement(shot.shot_id)?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  };
  useEffect(() => clearShotHighlight, []);

  const renderInline = (text: string) =>
    text.split(/(\[Image \d+\])/).map((part, partIndex) => {
      const match = /^\[Image (\d+)\]$/.exec(part);
      if (!match) return <span key={partIndex}>{part}</span>;
      const index = Number(match[1]);
      const token = tokens.find((item) => item.index === index);
      if (!token) {
        return (
          <span
            key={partIndex}
            className="mx-0.5 inline-flex items-center rounded-full border border-dashed border-[var(--color-danger)]/50 bg-[var(--color-bg-primary)] px-2 py-0.5 align-[-3px] font-mono text-[9px] font-bold leading-none text-[var(--color-danger)]"
          >
            {t("r2v.tokenMissing", { index })}
          </span>
        );
      }
      return (
        <button
          key={partIndex}
          type="button"
          data-prompt-token={index}
          title={token.name}
          onClick={() =>
            token.thumbUrl ? setPreviewSrc(token.thumbUrl) : undefined
          }
          className="mx-0.5 inline-flex cursor-pointer select-none items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--color-accent)_35%,var(--color-border))] bg-[var(--color-bg-primary)] py-0.5 pl-0.5 pr-2 align-[-5px] text-[11px] leading-none shadow-xs transition-all hover:-translate-y-px hover:border-[var(--color-accent)] hover:shadow-[0_2px_8px_rgba(255,127,22,.18)]"
        >
          {token.thumbUrl && (
            <img
              src={token.thumbUrl}
              alt=""
              className="h-5 w-5 rounded-full border border-[var(--color-border)] object-cover"
            />
          )}
          <span className="font-mono text-[9px] font-bold text-[var(--color-accent)]">
            IMG {index}
          </span>
          <span className="max-w-[108px] truncate font-medium text-[var(--color-text-primary)]">
            {token.name}
          </span>
        </button>
      );
    });

  return (
    <div
      data-creator-field={field}
      data-creator-path={path}
      data-creator-field-label={label}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-[11px] font-medium text-[var(--color-text-tertiary)]">
          {label}
          {charCount > 0 && (
            <span className="ml-1.5 text-[10px] text-[var(--color-text-tertiary)]/80">
              {t("r2v.promptChars", { count: charCount })}
            </span>
          )}
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
        <div
          ref={richRef}
          className="relative overflow-hidden px-3 py-2.5 text-xs leading-[2] text-[var(--color-text-primary)]"
          style={collapsed ? { maxHeight: collapseHeight } : undefined}
        >
          {value.trim() ? (
            segments.map((segment, segmentIndex) => {
              const shotNumber = segment.shotNumber;
              const shot =
                shotNumber && shotNumber > 0 ? shotOf(shotNumber) : null;
              return (
                <div
                  key={segmentIndex}
                  data-prompt-segment={shotNumber ?? "all"}
                  className={`whitespace-pre-wrap break-words rounded-sm border-l-2 border-transparent ${
                    marked ? "pl-2.5" : ""
                  } ${segmentIndex > 0 ? "mt-1.5" : ""}`}
                >
                  {marked && shotNumber === 0 && (
                    <span className="mr-1.5 inline-flex items-center rounded-full border border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-primary)] px-2 py-px align-[-2px] text-[10px] font-bold leading-normal text-[var(--color-text-secondary)]">
                      {t("r2v.segOverview")}
                    </span>
                  )}
                  {marked && shotNumber !== null && shotNumber > 0 && (
                    <button
                      type="button"
                      data-shot-link={shotNumber}
                      title={t("r2v.shotBadgeTitle")}
                      onMouseEnter={() => highlightShot(shotNumber)}
                      onMouseLeave={clearShotHighlight}
                      onClick={() => scrollToShot(shotNumber)}
                      className="mr-1.5 inline-flex items-center gap-1 rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-primary)] px-2 py-px align-[-2px] text-[10px] font-bold leading-normal text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                    >
                      SHOT {shotNumber}
                      {shot && (
                        <span className="font-medium text-[var(--color-text-tertiary)]">
                          {[
                            shot.framing?.trim(),
                            shot.duration_seconds != null
                              ? `${shot.duration_seconds}s`
                              : null,
                          ]
                            .filter(Boolean)
                            .map((meta) => `· ${meta}`)
                            .join(" ")}
                        </span>
                      )}
                    </button>
                  )}
                  {renderInline(segment.text)}
                </div>
              );
            })
          ) : (
            <span className="text-[var(--color-text-tertiary)]">
              {placeholder ?? t("r2v.generateAndEdit", { label })}
            </span>
          )}
          {collapsed && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-b from-transparent to-[var(--color-bg-secondary)]" />
          )}
        </div>

        {/* Keep the TextArea mounted (hidden) so data-creator anchors, review
            focus and controlled edits survive; the fullscreen editor is the
            only user-facing edit surface. */}
        <div className="hidden">
          <TextArea
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            autoSize={{ minRows: 3, maxRows: 16 }}
            placeholder={placeholder ?? t("r2v.generateAndEdit", { label })}
            className="!rounded-none !border-0 !bg-transparent !text-xs !shadow-none"
          />
        </div>

        {/* Design 84:39555: the action row lives inside the prompt card,
            bottom-right, gap 12 — 编辑 pill left of the regenerate pill. */}
        <div className="flex justify-end gap-3 px-3 pb-3 pt-1.5">
          <button
            type="button"
            data-prompt-edit={field}
            disabled={disabled}
            onClick={() => setFullOpen(true)}
            className="inline-flex h-10 shrink-0 cursor-pointer select-none items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-4 text-sm font-medium leading-6 text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-border-strong)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <SquarePen className="h-5 w-5" />
            {t("r2v.fullscreenEdit")}
          </button>
          {onRegenerate && (
            <RegeneratePill
              field={field}
              label={regenerateLabel ?? ""}
              loading={regenerating}
              disabled={disabled}
              onClick={onRegenerate}
            />
          )}
        </div>
      </div>

      {overflowing && (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="mt-1 block w-full text-center text-[10.5px] font-semibold text-[var(--color-accent)] hover:underline"
        >
          {expanded
            ? t("r2v.collapse")
            : t("r2v.expandAll", { count: charCount })}
        </button>
      )}
      {segMismatch && (
        <p className="mt-1.5 text-[10px] text-[var(--color-warning)]">
          {t("r2v.segMismatch", {
            segments: shotSegmentCount,
            shots: shots?.length ?? 0,
          })}
        </p>
      )}
      <InlineReviewDiff pointer={path} />

      {/* Controlled zoom preview for token thumbnails. */}
      {previewSrc && (
        <Image
          style={{ display: "none" }}
          src={previewSrc}
          preview={{
            visible: true,
            src: previewSrc,
            onVisibleChange: (visible) => {
              if (!visible) setPreviewSrc(null);
            },
          }}
        />
      )}

      <PromptEditorModal
        open={fullOpen}
        label={label}
        initialValue={value}
        tokens={tokens}
        disabled={disabled}
        onCancel={() => setFullOpen(false)}
        onDone={(next) => {
          onChange(next);
          setFullOpen(false);
          onEditComplete?.();
        }}
      />
    </div>
  );
}
