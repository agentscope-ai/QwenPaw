import { useTranslation } from "react-i18next";

import type {
  MotionGraphicDocument,
  ProjectSettingsDocument,
  SubtitleAnimationPolicy,
} from "@/contracts/creator";
import SubtitleAnimationControls, {
  CAPTION_ENTRANCE_CHOICES,
  CAPTION_EXIT_CHOICES,
} from "./SubtitleAnimationControls";
import SubtitleStyleControls from "./SubtitleStyleControls";
import SubtitleTemplatePicker, {
  subtitlePackNameKey,
} from "./SubtitleTemplatePicker";
import {
  subtitleStyleDraftDirtyCount,
  type SubtitleStyleDraft,
} from "./subtitleStyleDraft";

export { subtitleStyleFromSettings } from "./subtitleStyleDraft";
export type { SubtitleStyleDraft } from "./subtitleStyleDraft";

/**
 * The subtitle style bar outside the creation flow.
 *
 * A pick here is only a pick: the controls write into the draft the detail
 * panel owns, and nothing reaches the backend until its 确认修改 button turns
 * the difference against ``base`` into one style call — the route keeps the
 * project setting, the burned-in caption documents and each subtitle's 动效描
 * 述 in step, so a stray click must not redraw every caption (and drop the
 * composed master) on its own.  The bar never keeps a draft of its own either:
 * the project document stays the only source of what is currently in effect,
 * which is what the 「当前生效」 line reports.
 */

interface SubtitleStyleSectionProps {
  settings: ProjectSettingsDocument;
  /** What the project plays today; the draft is measured against it. */
  base: SubtitleStyleDraft;
  /** The user's picks, not yet sent. */
  draft: SubtitleStyleDraft;
  onDraftChange: (draft: SubtitleStyleDraft) => void;
  /**
   * Whether the addressed captions' look comes from the deterministic caption
   * template.  False hides the motion picker: a picker that can never move its
   * target is worse than a sentence that says who owns the look.
   */
  motionOwned?: boolean;
  /**
   * True when the motion picker addresses one caption only (the detail view)
   * while the pack and the overrides stay project-wide — a promise the route
   * enforces, so the bar has to say it out loud.
   */
  elementScoped?: boolean;
  busy?: boolean;
  /**
   * Whether the entrance / exit / loop picker is offered at all.
   *
   * The caption renderer delivers the entrance / exit / loop frame sequences,
   * so the picker is live wherever its pick can land: hosts whose settings
   * document carries no animation field (the creation modal) still opt out,
   * because a picker whose pick never persists is exactly the "my setting did
   * nothing" report.
   */
  showMotion?: boolean;
}

/**
 * Whether the caption style bar may redraw this document at all.
 *
 * Mirrors backend ``caption_owned_template``: only the deterministic
 * ``caption_card`` template is derived data.  A VLM ``html_js`` lettering, a
 * blueprint 花字 or an authored card owns a look no style pack overwrites, so
 * the route refuses to touch it and reports it as skipped.
 */
export function captionDocumentOwnedByStyle(
  motion: MotionGraphicDocument | null | undefined,
): boolean {
  return Boolean(
    motion &&
      motion.format === "html_css" &&
      motion.motif === "caption_card" &&
      motion.template_version != null,
  );
}

/**
 * What one caption document plays today, read the way the renderer reads it.
 *
 * Entrance and exit are document fields; the ambient loop is deliberately not
 * a document field (a tiled document would replay the entrance), so it lives
 * in the ``caption_animation=`` stamp the backend writes into design notes.
 * A document this pipeline never drew carries no stamp and reports nothing,
 * which keeps the pickers honest about "follow the style pack".
 */
export function subtitleAnimationFromDocument(
  motion: MotionGraphicDocument | null | undefined,
): SubtitleAnimationPolicy | null {
  if (!motion) return null;
  if (motion.format !== "html_css" || motion.motif !== "caption_card") {
    return null;
  }
  const stamp = /caption_animation=([^\s\n]*)/.exec(
    motion.design_notes ?? "",
  )?.[1];
  if (!stamp) return null;
  const [entrance, exit, loop] = stamp.split("/");
  // A token outside the renderer's vocabulary can only come from a damaged or
  // future document; casting it through would light up a pill the picker
  // cannot send back, so unknown parts simply read as "follow the pack".
  return {
    entrance:
      CAPTION_ENTRANCE_CHOICES.find((choice) => choice.id === entrance)?.id ??
      null,
    exit: CAPTION_EXIT_CHOICES.find((choice) => choice.id === exit)?.id ?? null,
    loop: loop === "1",
  };
}

export function SubtitleStyleSection({
  settings,
  base,
  draft,
  onDraftChange,
  motionOwned = true,
  elementScoped = false,
  busy = false,
  showMotion = false,
}: SubtitleStyleSectionProps) {
  const { t } = useTranslation();
  const packId = settings.subtitle_template ?? null;
  const pending = subtitleStyleDraftDirtyCount(draft, base);

  return (
    <div
      data-subtitle-style-section
      className="flex flex-col gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-container)] p-3"
    >
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold text-[var(--color-text-primary)]">
            {t("home.subtitleTemplateLabel")}
          </span>
          <span className="text-[11px] text-[var(--color-text-tertiary)]">
            {t("plan.subtitleStyleCurrent", {
              name: t(subtitlePackNameKey(packId)),
            })}
          </span>
        </div>
        {/* Say out loud that a pick is still only a pick, otherwise the
            highlighted pill reads as a finished change. */}
        {pending > 0 && (
          <span
            data-subtitle-style-pending
            className="text-[11px] text-[var(--color-accent)]"
          >
            {t("plan.subtitleStylePending", { count: pending })}
          </span>
        )}
      </div>

      <SubtitleTemplatePicker
        value={draft.packId}
        onChange={(id) => onDraftChange({ ...draft, packId: id })}
        style={draft.style}
        animation={draft.animation}
        onSelectCustom={(custom) =>
          onDraftChange({
            ...draft,
            packId: custom.packId ?? null,
            style: custom.style ?? null,
            animation: custom.animation ?? null,
          })
        }
      />

      <SubtitleStyleControls
        value={draft.style}
        onChange={(style) => onDraftChange({ ...draft, style })}
      />

      {showMotion &&
        (motionOwned ? (
          <SubtitleAnimationControls
            value={draft.animation ?? null}
            onChange={(animation) => onDraftChange({ ...draft, animation })}
            disabled={busy}
          />
        ) : (
          <span className="text-[11px] text-[var(--color-text-tertiary)]">
            {t("plan.subtitleStyleMotionUnowned")}
          </span>
        ))}
      {showMotion && elementScoped && motionOwned ? (
        <span className="text-[11px] text-[var(--color-text-tertiary)]">
          {t("plan.subtitleStyleElementScope")}
        </span>
      ) : null}
    </div>
  );
}

export default SubtitleStyleSection;
