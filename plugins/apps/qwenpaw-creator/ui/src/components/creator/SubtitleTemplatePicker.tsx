import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { Input, message, Modal, Popconfirm, Tooltip } from "antd";

import {
  deleteUserSubtitleStyle,
  listUserSubtitleStyles,
  saveUserSubtitleStyle,
  updateUserSubtitleStyle,
  type UserSubtitleStyleBundle,
} from "@/api/creator/subtitleStyles";
import { creatorRequest } from "@/api/creator/client";
import type {
  SubtitleAnimationPolicy,
  SubtitleStyle,
  UserSubtitleStyle,
} from "@/contracts/creator";
import { CAPTION_ENTRANCE_CHOICES } from "./SubtitleAnimationControls";
import { FONT_PREVIEW_STACKS } from "./SubtitleStyleControls";

/**
 * Preview parameters of one subtitle style pack, exactly as the backend's
 * deterministic renderer paints them. Mirrors one item of the backend
 * ``subtitle_pack_preview_specs()`` payload.
 */
export interface SubtitlePackPreviewSpec {
  id: string | null;
  fontFamily: string;
  fontWeight: number;
  letterSpacing: string;
  lineHeight: number;
  strokeScale: number;
  tiltDeg: number;
  plate: string;
  plateRadius: string;
  glow: boolean;
  entrance: string;
  loop: boolean;
}

/**
 * Fallback mirror of backend ``subtitle_pack_preview_specs()`` (same order,
 * same values): the cards still paint the renderer's look when the preview
 * endpoint is unreachable — tests, stale hosts. The backend stays the single
 * source of truth; this table follows it.
 */
export const SUBTITLE_TEMPLATE_PACKS: SubtitlePackPreviewSpec[] = [
  {
    id: "variety_pop",
    fontFamily: "'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif",
    fontWeight: 800,
    letterSpacing: "0.02em",
    lineHeight: 1.25,
    strokeScale: 1.35,
    tiltDeg: 0,
    plate: "",
    plateRadius: "0.28em",
    glow: false,
    entrance: "pop",
    loop: true,
  },
  {
    id: "cinematic",
    fontFamily: "'Songti SC','Noto Serif CJK SC','SimSun',serif",
    fontWeight: 500,
    letterSpacing: "0.18em",
    lineHeight: 1.5,
    strokeScale: 0.6,
    tiltDeg: 0,
    plate: "",
    plateRadius: "0.28em",
    glow: false,
    entrance: "slide",
    loop: false,
  },
  {
    id: "clean_talk",
    fontFamily: "'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif",
    fontWeight: 600,
    letterSpacing: "0.01em",
    lineHeight: 1.35,
    strokeScale: 0.4,
    tiltDeg: 0,
    plate: "rgba(14,16,20,0.42)",
    plateRadius: "0.34em",
    glow: false,
    entrance: "soft_fade",
    loop: false,
  },
  {
    id: "warm_note",
    fontFamily: "'Kaiti SC','STKaiti','Noto Serif CJK SC',serif",
    fontWeight: 500,
    letterSpacing: "0.04em",
    lineHeight: 1.45,
    strokeScale: 0.5,
    tiltDeg: 0,
    plate: "rgba(255,248,232,0.5)",
    plateRadius: "0.18em",
    glow: false,
    entrance: "type_on",
    loop: false,
  },
  {
    id: "neon_music",
    fontFamily: "'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif",
    fontWeight: 700,
    letterSpacing: "0.06em",
    lineHeight: 1.3,
    strokeScale: 0.8,
    tiltDeg: 0,
    plate: "rgba(10,8,24,0.42)",
    plateRadius: "0.28em",
    glow: true,
    entrance: "pop",
    loop: true,
  },
];

/** The "smart recommend" card: the historical plain-subtitle look. */
export const SMART_SUBTITLE_PREVIEW: SubtitlePackPreviewSpec = {
  id: null,
  fontFamily:
    "'Noto Sans CJK SC','Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif",
  fontWeight: 600,
  letterSpacing: "0em",
  lineHeight: 1.35,
  strokeScale: 1,
  tiltDeg: 0,
  plate: "",
  plateRadius: "0.28em",
  glow: false,
  entrance: "soft_fade",
  loop: false,
};

const PACK_I18N_KEYS: Record<string, { nameKey: string; descKey: string }> = {
  variety_pop: {
    nameKey: "home.subtitleTemplateVarietyPop",
    descKey: "home.subtitleTemplateVarietyPopDesc",
  },
  cinematic: {
    nameKey: "home.subtitleTemplateCinematic",
    descKey: "home.subtitleTemplateCinematicDesc",
  },
  clean_talk: {
    nameKey: "home.subtitleTemplateCleanTalk",
    descKey: "home.subtitleTemplateCleanTalkDesc",
  },
  warm_note: {
    nameKey: "home.subtitleTemplateWarmNote",
    descKey: "home.subtitleTemplateWarmNoteDesc",
  },
  neon_music: {
    nameKey: "home.subtitleTemplateNeonMusic",
    descKey: "home.subtitleTemplateNeonMusicDesc",
  },
};

/** i18n key of one card's name; unknown and null ids read as smart recommend. */
export function subtitlePackNameKey(packId: string | null): string {
  return PACK_I18N_KEYS[packId ?? ""]?.nameKey ?? "home.subtitleTemplateSmart";
}

/** i18n key of one card's scene description. */
export function subtitlePackDescKey(packId: string | null): string {
  return (
    PACK_I18N_KEYS[packId ?? ""]?.descKey ?? "home.subtitleTemplateSmartDesc"
  );
}

// ── same formulas as backend motion_templates ──
function captionEm(value: number): string {
  let text = value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  if (text.startsWith("0.")) text = text.slice(1);
  return text ? `${text}em` : "0em";
}

function captionShadowStack(
  stroke: number,
  glow: boolean,
  colour: string,
): string {
  const parts: string[] = [];
  if (stroke > 0) {
    parts.push(`0 ${captionEm(0.025 * stroke)} ${captionEm(0.05 * stroke)} #000d`);
    parts.push(`0 ${captionEm(0.04 * stroke)} ${captionEm(0.14 * stroke)} #000b`);
  }
  if (glow) {
    const halo = colour.startsWith("#") ? colour : "#ffffff";
    parts.push(`0 0 .06em ${halo}`, `0 0 .18em ${halo}88`, `0 0 .38em ${halo}55`);
  }
  return parts.length ? parts.join(",") : "none";
}

function plateWithOpacity(
  plate: string,
  opacity: number | null | undefined,
): string {
  if (!plate) return "";
  if (opacity === null || opacity === undefined) return plate;
  const alpha = Math.max(0, Math.min(1, opacity));
  if (alpha <= 0) return "";
  const match = /^rgba?\((\d+),(\d+),(\d+)/.exec(plate);
  if (!match) return plate;
  return `rgba(${match[1]},${match[2]},${match[3]},${alpha.toFixed(3)})`;
}

const ENTRANCE_ANIMATION: Record<string, string> = {
  pop: "capPop .28s cubic-bezier(.34,1.56,.64,1) both",
  slide: "capSlide .3s ease-out both",
  type_on: "capType .5s linear both",
};
// Same source as backend ``_caption_entrance_css`` plus the ambient breath
// loop; remounting the words node (hover / select) replays the entrance.
const PREVIEW_KEYFRAMES =
  "@keyframes capPop{from{opacity:.6;transform:scale(.88)}" +
  "to{opacity:1;transform:scale(1)}}" +
  "@keyframes capSlide{from{opacity:.6;transform:translateY(.45em)}" +
  "to{opacity:1;transform:translateY(0)}}" +
  "@keyframes capType{from{opacity:.85;clip-path:inset(0 62% 0 0)}" +
  "to{opacity:1;clip-path:inset(0 0 0 0)}}" +
  "@keyframes capAppear{from{opacity:.72}to{opacity:1}}" +
  "@keyframes capBreath{0%,100%{transform:scale(1)}12%{transform:scale(1.022)}" +
  "25%{transform:scale(1)}37%{transform:scale(1.018)}50%{transform:scale(1)}" +
  "62%{transform:scale(1.022)}75%{transform:scale(1)}87%{transform:scale(1.014)}}";
// A stand-in video frame: the previews must sit on footage-like darkness,
// otherwise plate alpha and glow read nothing like the final pixels.
const PREVIEW_FRAME_BACKGROUND =
  "radial-gradient(120% 90% at 20% 10%, rgba(255,196,120,0.55), transparent 60%)," +
  "radial-gradient(90% 80% at 85% 80%, rgba(64,120,190,0.5), transparent 65%)," +
  "linear-gradient(160deg, #4a5568 0%, #232a36 55%, #10141b 100%)";

/** Normalised signature of the five style overrides, nulls included. */
function styleSignature(style: SubtitleStyle | null | undefined): string {
  return JSON.stringify({
    color: style?.color ?? null,
    fontScale: style?.fontScale ?? null,
    strokeScale: style?.strokeScale ?? null,
    backgroundOpacity: style?.backgroundOpacity ?? null,
    // `default` and an absent pick are the same face (the pack's own); any
    // other id is a real difference a saved card must see, or two bundles
    // differing only by font both light up.
    fontFamily:
      style?.fontFamily && style.fontFamily !== "default"
        ? style.fontFamily
        : null,
  });
}

/** Normalised signature of the entrance / exit / loop triple. */
function motionSignature(
  animation: SubtitleAnimationPolicy | null | undefined,
): string {
  return JSON.stringify({
    entrance: animation?.entrance ?? null,
    exit: animation?.exit ?? null,
    loop: animation?.loop ?? null,
  });
}

/** Whether the window right now shows exactly what this bundle saved. */
function customMatchesCurrent(
  custom: UserSubtitleStyle,
  value: string | null,
  style: SubtitleStyle | null,
  animation: SubtitleAnimationPolicy | null | undefined,
): boolean {
  return (
    (custom.packId ?? null) === value &&
    styleSignature(custom.style) === styleSignature(style) &&
    motionSignature(custom.animation) === motionSignature(animation)
  );
}

interface SubtitleTemplatePickerProps {
  value: string | null;
  onChange: (id: string | null) => void;
  /** Live draft of the style window's four control groups; previews follow. */
  style?: SubtitleStyle | null;
  /** Live motion triple; saved bundles light up when everything matches. */
  animation?: SubtitleAnimationPolicy | null;
  /**
   * Apply a saved bundle (pack + overrides + motion) in one move.  Hosts
   * that cannot persist the triple leave it out and the saved cards fall
   * back to switching only the base pack.
   */
  onSelectCustom?: (custom: UserSubtitleStyle) => void;
}

/** Horizontal JianYing-style subtitle template strip shown for "auto". */
export function SubtitleTemplatePicker({
  value,
  onChange,
  style = null,
  animation = null,
  onSelectCustom,
}: SubtitleTemplatePickerProps) {
  const { t } = useTranslation();
  const [packSpecs, setPackSpecs] = useState<SubtitlePackPreviewSpec[] | null>(
    null,
  );
  const [customStyles, setCustomStyles] = useState<UserSubtitleStyle[]>([]);
  const [replay, setReplay] = useState<Record<string, number>>({});
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDesc, setSaveDesc] = useState("");

  const refreshCustom = useCallback(() => {
    listUserSubtitleStyles()
      .then((body) => setCustomStyles(body?.items ?? []))
      .catch(() => setCustomStyles([]));
  }, []);

  useEffect(() => {
    let alive = true;
    creatorRequest<{ items?: SubtitlePackPreviewSpec[] }>(
      "/subtitle-packs/preview",
      {},
      { timeoutMs: 8000 },
    )
      .then((body) => {
        const items = (body?.items ?? []).filter((item) => item && item.id);
        if (alive && items.length > 0) setPackSpecs(items);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    refreshCustom();
  }, [refreshCustom]);

  const specs = useMemo(
    () => [SMART_SUBTITLE_PREVIEW, ...(packSpecs ?? SUBTITLE_TEMPLATE_PACKS)],
    [packSpecs],
  );

  // Every bundle equal to the current picks lights up: two saves can hold
  // identical content, and lighting only the first made clicking its twin
  // look like a no-op.  Built-ins stay dark while any custom matches.
  const matchedCustomIds = useMemo(
    () =>
      new Set(
        customStyles
          .filter((custom) =>
            customMatchesCurrent(custom, value, style, animation),
          )
          .map((custom) => custom.styleId),
      ),
    [customStyles, value, style, animation],
  );

  interface CardEntry {
    cardKey: string;
    spec: SubtitlePackPreviewSpec;
    /** Override source of one miniature: the draft, or the saved bundle. */
    cardStyle: SubtitleStyle | null;
    custom?: UserSubtitleStyle;
    selected: boolean;
  }
  const entries: CardEntry[] = [
    ...specs.map((spec) => ({
      cardKey: spec.id ?? "smart",
      spec,
      cardStyle: style,
      selected: value === spec.id && matchedCustomIds.size === 0,
    })),
    ...customStyles.map((custom) => {
      const base =
        specs.find((spec) => spec.id === (custom.packId ?? null)) ?? specs[0];
      return {
        cardKey: custom.styleId,
        spec: {
          ...base,
          entrance: custom.animation?.entrance ?? base.entrance,
          loop: custom.animation?.loop ?? base.loop,
        },
        cardStyle: custom.style ?? null,
        custom,
        selected: matchedCustomIds.has(custom.styleId),
      };
    }),
  ];

  const currentBundle = (
    name: string,
    description = "",
  ): UserSubtitleStyleBundle => ({
    name,
    description,
    packId: value,
    style: style ?? null,
    animation: animation ?? null,
  });

  const handleSave = () => {
    saveUserSubtitleStyle(currentBundle(saveName.trim(), saveDesc.trim()))
      .then(() => {
        setSaveOpen(false);
        refreshCustom();
      })
      .catch(() => undefined);
  };
  const handleUpdate = (custom: UserSubtitleStyle) => {
    updateUserSubtitleStyle(
      custom.styleId,
      currentBundle(custom.name, custom.description ?? ""),
    )
      .then(refreshCustom)
      .catch(() => undefined);
  };
  const handleDelete = (custom: UserSubtitleStyle) => {
    deleteUserSubtitleStyle(custom.styleId)
      .then(refreshCustom)
      .catch(() => undefined);
  };

  return (
    <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
      <style>{PREVIEW_KEYFRAMES}</style>
      {entries.map((entry) => {
        const { spec, custom } = entry;
        const cardKey = entry.cardKey;
        const selected = entry.selected;
        const cardColour = entry.cardStyle?.color || "#ffffff";
        const cardFontScale = entry.cardStyle?.fontScale ?? 1;
        const stroke = Math.max(
          0,
          spec.strokeScale * (entry.cardStyle?.strokeScale ?? 1),
        );
        const cardBgOpacity = entry.cardStyle?.backgroundOpacity ?? null;
        const plate = plateWithOpacity(spec.plate, cardBgOpacity);
        // Colour, size, outline and plate already speak the draft; the face
        // was the one control still painted from the pack, so picking 宋体
        // changed the film but not the card.  Auto keeps the pack's own face,
        // exactly what the renderer does for a null/default pick.
        const pickedFamily = entry.cardStyle?.fontFamily ?? null;
        const cardFontFamily =
          pickedFamily && FONT_PREVIEW_STACKS[pickedFamily]
            ? FONT_PREVIEW_STACKS[pickedFamily]
            : spec.fontFamily;
        const wordsStyle: CSSProperties = {
          color: cardColour,
          fontFamily: cardFontFamily,
          fontSize: `${(15 * cardFontScale).toFixed(1)}px`,
          fontWeight: spec.fontWeight,
          lineHeight: spec.lineHeight,
          letterSpacing: spec.letterSpacing,
          textShadow: captionShadowStack(stroke, spec.glow, cardColour),
          ...(plate
            ? {
                display: "inline-block",
                padding: ".28em .6em",
                background: plate,
                borderRadius: spec.plateRadius || "0.28em",
                maxWidth: "100%",
              }
            : { width: "100%" }),
          animation:
            (ENTRANCE_ANIMATION[spec.entrance] ?? "capAppear .14s linear both") +
            (spec.loop ? ",capBreath 9.6s ease-in-out .45s infinite" : ""),
        };
        // Name the face the way the font picker above names it, so the
        // footnote never asks a reader to decode sans/serif vocabulary.
        const family = cardFontFamily.includes("Songti")
          ? t("home.subtitleStyleFontSong")
          : cardFontFamily.includes("Kaiti")
            ? t("home.subtitleStyleFontKai")
            : t("home.subtitleStyleFontHei");
        // Name the pack's numeric weight the way 字号 names its size, so the
        // footnote reads 特粗/粗/半粗 instead of a bare 800/700/600.
        const weightLabel =
          spec.fontWeight >= 750
            ? t("home.subtitlePreviewWeightExtrabold")
            : spec.fontWeight >= 650
              ? t("home.subtitlePreviewWeightBold")
              : spec.fontWeight >= 550
                ? t("home.subtitlePreviewWeightSemibold")
                : spec.fontWeight >= 450
                  ? t("home.subtitlePreviewWeightMedium")
                  : t("home.subtitlePreviewWeightRegular");
        const plateAlpha = parseFloat(spec.plate.split(",")[3] ?? "0") || 0;
        const plateText = !spec.plate
          ? t("home.subtitlePreviewPlateNone")
          : cardBgOpacity === 0
            ? t("home.subtitlePreviewPlateOff")
            : t("home.subtitlePreviewPlatePct", {
                percent: Math.round((cardBgOpacity ?? plateAlpha) * 100),
              });
        // The footnote speaks the user's language: the raw entrance id
        // (soft_fade / pop / ...) reads as machine noise next to the pills.
        const entranceKey = CAPTION_ENTRANCE_CHOICES.find(
          (choice) => choice.id === spec.entrance,
        )?.key;
        // The miniature plate is always footage-dark, so the chips carry
        // their own light ground; theme vars vanish against it.
        const actionClass =
          "cursor-pointer rounded bg-white/90 px-1.5 py-0.5 text-[10px] leading-4 shadow transition-colors hover:bg-white";
        const cardButton = (
          <button
            key={custom ? undefined : cardKey}
            type="button"
            aria-pressed={selected}
            onClick={() => {
              if (!custom) {
                onChange(spec.id);
                return;
              }
              if (onSelectCustom) onSelectCustom(custom);
              else onChange(custom.packId ?? null);
              // A snapshot equal to the current picks changes nothing on
              // screen; the toast answers the click either way.
              message.success(
                t("home.subtitleCustomApplied", { name: custom.name }),
              );
            }}
            onMouseEnter={() =>
              setReplay((current) => ({
                ...current,
                [cardKey]: (current[cardKey] ?? 0) + 1,
              }))
            }
            className={`flex flex-col gap-1 rounded-lg border p-2 text-left transition-colors ${
              custom ? "h-full w-full" : "min-w-[168px] flex-1"
            } ${
              selected
                ? "border-[var(--color-text-primary)] bg-[rgba(43,27,0,0.06)] dark:bg-white/10"
                : "border-transparent bg-[rgba(43,27,0,0.03)] hover:bg-[rgba(43,27,0,0.06)] dark:bg-white/5 dark:hover:bg-white/10"
            }`}
          >
            <span
              className="relative block h-24 overflow-hidden rounded-md"
              style={{ background: PREVIEW_FRAME_BACKGROUND }}
            >
              <span
                className="absolute inset-[6%] z-[1] flex items-center justify-center"
                style={
                  spec.tiltDeg
                    ? { transform: `rotate(${spec.tiltDeg}deg)` }
                    : undefined
                }
              >
                <span
                  key={replay[cardKey] ?? 0}
                  data-subtitle-preview={cardKey}
                  className="text-center"
                  style={wordsStyle}
                >
                  {t("home.subtitlePreviewSampleA")}
                  <br />
                  {t("home.subtitlePreviewSampleB")}
                </span>
              </span>
            </span>
            <span className="flex items-center gap-1 text-xs font-semibold text-[var(--color-text-primary)]">
              {custom ? custom.name : t(subtitlePackNameKey(spec.id))}
              {custom ? (
                <span className="rounded border border-[var(--color-border)] px-1 text-[10px] font-normal leading-4 text-[var(--color-text-tertiary)]">
                  {t("home.subtitleCustomBadge")}
                </span>
              ) : null}
            </span>
            <span className="text-[11px] leading-4 text-[var(--color-text-tertiary)]">
              {custom?.description ||
                t(subtitlePackDescKey(custom ? (custom.packId ?? null) : spec.id))}
            </span>
            <span className="font-mono text-[10px] leading-[14px] text-[var(--color-text-tertiary)]">
              {t("home.subtitlePreviewMeta", {
                family,
                weight: weightLabel,
                spacing: spec.letterSpacing,
                stroke: stroke.toFixed(2),
                plate: plateText,
                entrance: entranceKey ? t(entranceKey) : spec.entrance,
                loop: spec.loop ? t("home.subtitlePreviewLoop") : "",
              })}
            </span>
          </button>
        );
        if (!custom) return cardButton;
        return (
          <div key={cardKey} className="group relative min-w-[168px] flex-1">
            <Tooltip title={t("home.subtitleCustomCardHint")}>
              {cardButton}
            </Tooltip>
            {/* Always on: hover-only hid them from discovery.  Above the
                miniature's z-[1] plate, or clicks land on the preview. */}
            <span className="absolute right-1 top-1 z-[2] flex items-center gap-1">
              <button
                type="button"
                onClick={() => handleUpdate(custom)}
                className={`${actionClass} text-gray-700 hover:text-gray-900`}
              >
                {t("home.subtitleCustomUpdate")}
              </button>
              <Popconfirm
                title={t("home.subtitleCustomDeleteConfirm")}
                okText={t("home.subtitleCustomDelete")}
                cancelText={t("common.cancel")}
                onConfirm={() => handleDelete(custom)}
              >
                <button
                  type="button"
                  className={`${actionClass} text-red-600 hover:text-red-700`}
                >
                  {t("home.subtitleCustomDelete")}
                </button>
              </Popconfirm>
            </span>
          </div>
        );
      })}
      {onSelectCustom ? (
        <button
          type="button"
          onClick={() => {
            setSaveName("");
            setSaveDesc("");
            setSaveOpen(true);
          }}
          className="flex min-w-[120px] flex-1 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[var(--color-border)] p-2 text-[11px] text-[var(--color-text-tertiary)] transition-colors hover:border-[var(--color-text-secondary)] hover:text-[var(--color-text-secondary)]"
        >
          + {t("home.subtitleCustomSave")}
        </button>
      ) : null}
      <Modal
        title={t("home.subtitleCustomSaveTitle")}
        open={saveOpen}
        onCancel={() => setSaveOpen(false)}
        onOk={handleSave}
        okText={t("common.ok")}
        cancelText={t("common.cancel")}
        okButtonProps={{ disabled: !saveName.trim() }}
      >
        <Input
          value={saveName}
          onChange={(event) => setSaveName(event.target.value)}
          placeholder={t("home.subtitleCustomName")}
        />
        <Input
          className="mt-2"
          value={saveDesc}
          onChange={(event) => setSaveDesc(event.target.value)}
          placeholder={t("home.subtitleCustomDesc")}
        />
      </Modal>
    </div>
  );
}

export default SubtitleTemplatePicker;
