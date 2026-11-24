import { useTranslation } from "react-i18next";

import type { SubtitleFontFamily, SubtitleStyle } from "@/contracts/creator";

/**
 * Colour / font-size / outline / background-block overrides for the standard
 * subtitle bar.
 *
 * Mirrors the backend ``SubtitleStyle`` model: every control keeps a
 * "default" choice mapped to ``null`` so an untouched project persists no
 * style at all and renders exactly as before. The values drive the
 * deterministic plain-subtitle renderer (PIL burn-in), the caption template
 * and their live preview; designed 花字 keeps its own per-footage styling.
 */

/** Swatches offered for the subtitle text colour. */
const COLOR_SWATCHES: string[] = [
  "#FFFFFF",
  "#FFE066",
  "#7DD3FC",
  "#86EFAC",
  "#FCA5A5",
  "#C4B5FD",
  "#1F2937",
];

/** Typeface choices; ``null`` is the renderer's auto sans CJK face. */
const FONT_CHOICES: Array<{ id: SubtitleFontFamily | null; key: string }> = [
  { id: null, key: "home.subtitleStyleFontAuto" },
  { id: "song", key: "home.subtitleStyleFontSong" },
  { id: "hei", key: "home.subtitleStyleFontHei" },
  { id: "kai", key: "home.subtitleStyleFontKai" },
];

/**
 * Per-family CSS stack so each pill previews its own face, the way the colour
 * swatches preview their colour.  Mirrors ``overlay._SUBTITLE_FONT_FAMILIES``
 * and the preview layer's stacks; the auto face (``null``) inherits the UI
 * sans, exactly what the renderer auto-detects.
 */
export const FONT_PREVIEW_STACKS: Record<string, string> = {
  song: '"Songti SC", "SimSun", "Noto Serif CJK SC", serif',
  hei: '"PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif',
  kai: '"Kaiti SC", "KaiTi", "STKaiti", "Noto Serif CJK SC", serif',
};

/** Font-size multiplier choices; ``null`` is the fitted base size. */
const SIZE_CHOICES: Array<{ id: number | null; key: string }> = [
  { id: 0.85, key: "home.subtitleStyleSizeSmall" },
  { id: null, key: "home.subtitleStyleSizeStandard" },
  { id: 1.25, key: "home.subtitleStyleSizeLarge" },
];

/** Outline-width multiplier choices; ``null`` is the base outline. */
const STROKE_CHOICES: Array<{ id: number | null; key: string }> = [
  { id: 0, key: "home.subtitleStyleStrokeNone" },
  { id: null, key: "home.subtitleStyleStrokeStandard" },
  { id: 1.8, key: "home.subtitleStyleStrokeThick" },
];

/**
 * Opacity of the background block a style pack draws behind the text; ``null``
 * keeps the pack's own alpha.  The pick reshapes the block a pack already
 * draws and never invents one, so a pack without a block (电影叙事…) looks
 * unchanged at every value — hence no per-pack branching here.
 */
const BACKGROUND_CHOICES: Array<{ id: number | null; key: string }> = [
  { id: null, key: "home.subtitleStyleBackgroundDefault" },
  { id: 0, key: "home.subtitleStyleBackgroundNone" },
  { id: 0.3, key: "home.subtitleStyleBackground30" },
  { id: 0.5, key: "home.subtitleStyleBackground50" },
  { id: 0.7, key: "home.subtitleStyleBackground70" },
  { id: 1, key: "home.subtitleStyleBackground100" },
];

interface SubtitleStyleControlsProps {
  value: SubtitleStyle | null;
  onChange: (style: SubtitleStyle | null) => void;
}

export function SubtitleStyleControls({
  value,
  onChange,
}: SubtitleStyleControlsProps) {
  const { t } = useTranslation();

  const color = value?.color ?? null;
  const fontFamily = value?.fontFamily ?? null;
  const fontScale = value?.fontScale ?? null;
  const strokeScale = value?.strokeScale ?? null;
  const backgroundOpacity = value?.backgroundOpacity ?? null;

  /** Merge one override, dropping the whole object back to ``null``. */
  const emit = (patch: Partial<SubtitleStyle>) => {
    const next: SubtitleStyle = {
      color: patch.color !== undefined ? patch.color : color,
      fontFamily:
        patch.fontFamily !== undefined ? patch.fontFamily : fontFamily,
      fontScale: patch.fontScale !== undefined ? patch.fontScale : fontScale,
      strokeScale:
        patch.strokeScale !== undefined ? patch.strokeScale : strokeScale,
      backgroundOpacity:
        patch.backgroundOpacity !== undefined
          ? patch.backgroundOpacity
          : backgroundOpacity,
    };
    const isDefault =
      next.color == null &&
      next.fontFamily == null &&
      next.fontScale == null &&
      next.strokeScale == null &&
      next.backgroundOpacity == null;
    onChange(isDefault ? null : next);
  };

  const pillBase =
    "cursor-pointer rounded-full border px-2.5 py-1 text-[11px] leading-4 transition-colors";
  const pillOn =
    "border-[var(--color-text-primary)] bg-[rgba(43,27,0,0.06)] font-semibold text-[var(--color-text-primary)] dark:bg-white/10";
  const pillOff =
    "border-transparent bg-[rgba(43,27,0,0.03)] text-[var(--color-text-secondary)] hover:bg-[rgba(43,27,0,0.06)] dark:bg-white/5 dark:hover:bg-white/10";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-[var(--color-text-tertiary)]">
          {t("home.subtitleStyle")}
        </span>
        {/* Mirrors the motion picker's 恢复默认: offered only while an override
            is stated, and it drops the whole style object back to null. */}
        {value != null ? (
          <button
            type="button"
            onClick={() => onChange(null)}
            className="cursor-pointer text-[11px] text-[var(--color-text-tertiary)] underline-offset-2 transition-colors hover:text-[var(--color-text-secondary)] hover:underline"
          >
            {t("home.subtitleStyleReset")}
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* Colour */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-[var(--color-text-tertiary)]">
            {t("home.subtitleStyleColor")}
          </span>
          <button
            type="button"
            aria-label={t("home.subtitleStyleColorDefault")}
            aria-pressed={color == null}
            onClick={() => emit({ color: null })}
            className={`${pillBase} ${color == null ? pillOn : pillOff}`}
          >
            {t("home.subtitleStyleColorDefault")}
          </button>
          {COLOR_SWATCHES.map((swatch) => (
            <button
              key={swatch}
              type="button"
              aria-label={swatch}
              aria-pressed={color === swatch}
              onClick={() => emit({ color: swatch })}
              className={`h-5 w-5 cursor-pointer rounded-full border transition-transform ${
                color === swatch
                  ? "border-[var(--color-text-primary)] scale-110"
                  : "border-[var(--color-border)] hover:scale-105"
              }`}
              style={{ backgroundColor: swatch }}
            />
          ))}
        </div>

        {/* Font family */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-[var(--color-text-tertiary)]">
            {t("home.subtitleStyleFont")}
          </span>
          {FONT_CHOICES.map((choice) => {
            const selected = fontFamily === choice.id;
            return (
              <button
                key={choice.key}
                type="button"
                aria-pressed={selected}
                onClick={() => emit({ fontFamily: choice.id })}
                className={`${pillBase} ${selected ? pillOn : pillOff}`}
                style={
                  choice.id
                    ? { fontFamily: FONT_PREVIEW_STACKS[choice.id] }
                    : undefined
                }
              >
                {t(choice.key)}
              </button>
            );
          })}
        </div>

        {/* Font size */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-[var(--color-text-tertiary)]">
            {t("home.subtitleStyleSize")}
          </span>
          {SIZE_CHOICES.map((choice) => {
            const selected = fontScale === choice.id;
            return (
              <button
                key={choice.key}
                type="button"
                aria-pressed={selected}
                onClick={() => emit({ fontScale: choice.id })}
                className={`${pillBase} ${selected ? pillOn : pillOff}`}
              >
                {t(choice.key)}
              </button>
            );
          })}
        </div>

        {/* Outline */}
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-[var(--color-text-tertiary)]">
            {t("home.subtitleStyleStroke")}
          </span>
          {STROKE_CHOICES.map((choice) => {
            const selected = strokeScale === choice.id;
            return (
              <button
                key={choice.key}
                type="button"
                aria-pressed={selected}
                onClick={() => emit({ strokeScale: choice.id })}
                className={`${pillBase} ${selected ? pillOn : pillOff}`}
              >
                {t(choice.key)}
              </button>
            );
          })}
        </div>

        {/* Background block opacity */}
        <div className="flex items-center gap-1.5">
          <span
            className="text-[11px] text-[var(--color-text-tertiary)]"
            title={t("home.subtitleStyleBackgroundHint")}
          >
            {t("home.subtitleStyleBackground")}
          </span>
          {BACKGROUND_CHOICES.map((choice) => {
            const selected = backgroundOpacity === choice.id;
            return (
              <button
                key={choice.key}
                type="button"
                aria-pressed={selected}
                onClick={() => emit({ backgroundOpacity: choice.id })}
                className={`${pillBase} ${selected ? pillOn : pillOff}`}
              >
                {t(choice.key)}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default SubtitleStyleControls;
