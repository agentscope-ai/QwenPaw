import { useTranslation } from "react-i18next";

import type { SubtitleAnimationPolicy } from "@/contracts/creator";

/**
 * Entrance / exit / loop picker for the standard subtitle bar.
 *
 * The three choices are exactly the vocabulary the caption renderer
 * understands (backend ``CAPTION_ENTRANCES`` and ``data-motion-exit``), so a
 * pick here is a promise the burned-in captions actually keep.  Leaving a
 * choice unset hands the decision to the selected style pack, which is why
 * the component never invents a default of its own.  Hosts whose policy is a
 * draft (the creation modal) pass ``allowClear`` so a pick can be taken back:
 * clicking the lit pill again unsets just that field, and once every field
 * is unset the whole policy collapses back to ``null`` — the pack decides.
 */

export type CaptionEntrance = NonNullable<SubtitleAnimationPolicy["entrance"]>;
export type CaptionExit = NonNullable<SubtitleAnimationPolicy["exit"]>;

/** Entrances the caption template can draw, in the order they are offered. */
export const CAPTION_ENTRANCE_CHOICES: Array<{
  id: CaptionEntrance;
  key: string;
}> = [
  { id: "soft_fade", key: "home.subtitleMotionEntranceFade" },
  { id: "pop", key: "home.subtitleMotionEntrancePop" },
  { id: "slide", key: "home.subtitleMotionEntranceSlide" },
  { id: "type_on", key: "home.subtitleMotionEntranceTypeOn" },
];

/** Exit choices; the composed master hands these to the caption track. */
export const CAPTION_EXIT_CHOICES: Array<{ id: CaptionExit; key: string }> = [
  { id: "none", key: "home.subtitleMotionExitNone" },
  { id: "soft_fade", key: "home.subtitleMotionExitFade" },
  { id: "shrink", key: "home.subtitleMotionExitShrink" },
];

const pillBase =
  "cursor-pointer rounded-full border px-2.5 py-1 text-[11px] leading-4 transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const pillOn =
  "border-[var(--color-text-primary)] bg-[rgba(43,27,0,0.06)] font-semibold text-[var(--color-text-primary)] dark:bg-white/10";
const pillOff =
  "border-transparent bg-[rgba(43,27,0,0.03)] text-[var(--color-text-secondary)] hover:bg-[rgba(43,27,0,0.06)] dark:bg-white/5 dark:hover:bg-white/10";
const labelClass = "text-[11px] text-[var(--color-text-tertiary)]";

interface PillRowProps<T extends string | boolean> {
  label: string;
  choices: Array<{ id: T; key: string }>;
  selected?: T | null;
  disabled?: boolean;
  onPick: (id: T) => void;
}

function PillRow<T extends string | boolean>({
  label,
  choices,
  selected,
  disabled,
  onPick,
}: PillRowProps<T>) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-1.5">
      <span className={labelClass}>{label}</span>
      {choices.map((choice) => (
        <button
          key={String(choice.id)}
          type="button"
          disabled={disabled}
          aria-pressed={selected === choice.id}
          onClick={() => onPick(choice.id)}
          className={`${pillBase} ${selected === choice.id ? pillOn : pillOff}`}
        >
          {t(choice.key)}
        </button>
      ))}
    </div>
  );
}

const LOOP_CHOICES: Array<{ id: boolean; key: string }> = [
  { id: false, key: "home.subtitleMotionLoopOff" },
  { id: true, key: "home.subtitleMotionLoopOn" },
];

interface SubtitleAnimationControlsProps {
  /** What the addressed captions currently play; ``null`` = pack default. */
  value: SubtitleAnimationPolicy | null;
  /** ``null`` comes back once every field is unset: the pack decides again. */
  onChange: (animation: SubtitleAnimationPolicy | null) => void;
  disabled?: boolean;
  /**
   * Offer the ways back to "pack decides": re-click a lit pill to unset it
   * and a 恢复默认 button to unset the whole policy.  Hosts that read a
   * settled stamp (the element detail) leave this off, because every field
   * of a stamp is a concrete value and the style wire has no "unset one".
   */
  allowClear?: boolean;
}

/** Whether any field still carries a pick of its own. */
function hasPick(policy: SubtitleAnimationPolicy | null | undefined): boolean {
  return (
    policy != null &&
    (policy.entrance != null || policy.exit != null || policy.loop != null)
  );
}

export function SubtitleAnimationControls({
  value,
  onChange,
  disabled = false,
  allowClear = false,
}: SubtitleAnimationControlsProps) {
  const { t } = useTranslation();
  const current = value ?? {};

  // Re-clicking the lit pill takes only that pick back; an emptied policy
  // collapses to null so the host sends nothing and the pack decides.
  const pick = <K extends "entrance" | "exit" | "loop">(
    field: K,
    id: NonNullable<SubtitleAnimationPolicy[K]>,
  ) => {
    const next: SubtitleAnimationPolicy = {
      ...current,
      [field]: allowClear && current[field] === id ? null : id,
    };
    onChange(hasPick(next) ? next : null);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-[var(--color-text-tertiary)]">
          {t("home.subtitleMotion")}
        </span>
        {allowClear && hasPick(value) ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(null)}
            className="cursor-pointer text-[11px] text-[var(--color-text-tertiary)] underline-offset-2 transition-colors hover:text-[var(--color-text-secondary)] hover:underline disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("home.subtitleMotionReset")}
          </button>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <PillRow
          label={t("home.subtitleMotionEntrance")}
          choices={CAPTION_ENTRANCE_CHOICES}
          selected={value?.entrance}
          disabled={disabled}
          onPick={(entrance) => pick("entrance", entrance)}
        />
        <PillRow
          label={t("home.subtitleMotionExit")}
          choices={CAPTION_EXIT_CHOICES}
          selected={value?.exit}
          disabled={disabled}
          onPick={(exit) => pick("exit", exit)}
        />
        <PillRow
          label={t("home.subtitleMotionLoop")}
          choices={LOOP_CHOICES}
          selected={value?.loop}
          disabled={disabled}
          onPick={(loop) => pick("loop", loop)}
        />
      </div>
      {!hasPick(value) && (
        <span className={labelClass}>
          {t("home.subtitleMotionPackDefault")}
        </span>
      )}
    </div>
  );
}

export default SubtitleAnimationControls;
