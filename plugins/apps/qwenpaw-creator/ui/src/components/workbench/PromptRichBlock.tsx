import { useEffect, useRef, useState } from "react";
import { Image, Input, Tooltip } from "antd";
import { Loader2, SquarePen, Wand2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";
import PromptEditorModal from "@/components/workbench/PromptEditorModal";
import { presentPromptEntityNames } from "@/lib/promptEntityNames";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { promptTokenAt } from "./promptReferenceTokens";

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
  /** Actual version identity; internal comparison only, never a public label. */
  referenceId?: string;
  /** Keep the index reserved when its referenced image cannot be resolved. */
  missing?: boolean;
}

/** Prompt text with actual reference previews and a full-screen editor. */
export default function PromptRichBlock({
  label,
  value,
  onChange,
  disabled = false,
  field,
  path,
  tokens,
  collapseHeight = 230,
  placeholder,
  onRegenerate,
  regenerating = false,
  regenerateDisabled = false,
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
  collapseHeight?: number;
  placeholder?: string;
  /** Design contract: the prompt card foots with one explicit regenerate
      action (再次生成图片 / 再次生成视频) that persists the edited prompt and
      re-dispatches the generation. */
  onRegenerate?: () => void;
  regenerating?: boolean;
  regenerateDisabled?: boolean;
  regenerateLabel?: string;
  /** Fired after the fullscreen editor's 完成 writes back — the editor lives
      in a portal, so the host's blur-capture auto-save never sees it. */
  onEditComplete?: () => void;
}) {
  const { t } = useTranslation();
  const project = useProjectSnapshotStore((state) => state.project);
  const presentedValue = presentPromptEntityNames(value, project);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const richRef = useRef<HTMLDivElement>(null);
  // 全屏编辑器（共享组件）：本地草稿，「完成」才写回。
  const [fullOpen, setFullOpen] = useState(false);

  const charCount = presentedValue.replace(/\s/g, "").length;
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
  }, [presentedValue, collapseHeight]);

  const renderInline = (text: string) =>
    text.split(/(\[Image \d+\])/).map((part, partIndex) => {
      const match = /^\[Image (\d+)\]$/.exec(part);
      if (!match) return <span key={partIndex}>{part}</span>;
      const index = Number(match[1]);
      const token = promptTokenAt(tokens, index);
      if (!token) {
        return (
          <span
            key={partIndex}
            data-prompt-token-missing={match[1]}
            className="mx-0.5 inline-flex items-center rounded-full border border-dashed border-[var(--color-danger)]/50 bg-[var(--color-bg-primary)] px-2 py-0.5 align-[-3px] font-mono text-[9px] font-bold leading-none text-[var(--color-danger)]"
          >
            {t("r2v.tokenMissing", { index: match[1] })}
          </span>
        );
      }
      return (
        <Tooltip
          key={partIndex}
          trigger={["hover", "focus"]}
          title={
            token.thumbUrl ? (
              <div className="max-w-[260px] space-y-1">
                <img
                  src={token.thumbUrl}
                  alt={token.name}
                  className="max-h-[220px] w-full rounded object-contain"
                />
                <div className="text-xs">{token.name}</div>
              </div>
            ) : (
              token.name
            )
          }
        >
          <button
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
        </Tooltip>
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
            <div
              data-prompt-segment="all"
              className="whitespace-pre-wrap break-words"
            >
              {renderInline(presentedValue)}
            </div>
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
        <div className="flex flex-wrap justify-end gap-3 px-3 pb-3 pt-1.5">
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
              disabled={disabled || regenerateDisabled}
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
        initialValue={presentedValue}
        sourceValue={value}
        sourceKey={path}
        tokens={tokens}
        disabled={disabled}
        onCancel={() => setFullOpen(false)}
        onDone={(next) => {
          // Opening and accepting an unchanged presentation must not rewrite
          // the stored prompt or make an existing generated artifact stale.
          onChange(next === presentedValue ? value : next);
          setFullOpen(false);
          onEditComplete?.();
        }}
      />
    </div>
  );
}
