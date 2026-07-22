import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Button,
  Card,
  Input,
  InputNumber,
  Slider,
} from "@agentscope-ai/design";
import {
  Check,
  Download,
  Plus,
  RotateCcw,
  Save,
  Star,
  Trash2,
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import {
  DEFAULT_THEME_COLORS,
  getThemePresetGradient,
  isBuiltInThemePreset,
  sortThemePresets,
  type ThemeColorKey,
  type ThemeColors,
  useTheme,
} from "../../../../contexts/ThemeContext";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import styles from "../index.module.less";

interface HslaColor {
  hue: number;
  saturation: number;
  lightness: number;
  alpha: number;
}

interface ColorTarget {
  key: ThemeColorKey;
  label: string;
  group: string;
  description: string;
  keywords: string[];
}

const COLOR_TARGETS: ColorTarget[] = [
  {
    key: "primary",
    label: "Brand primary",
    group: "Core",
    description: "Tabs, highlights, selected states",
    keywords: ["brand", "tabs", "active", "accent", "selected"],
  },
  {
    key: "link",
    label: "Links",
    group: "Core",
    description: "Links and inline actions",
    keywords: ["link", "anchor", "action"],
  },
  {
    key: "buttonBackground",
    label: "Primary buttons",
    group: "Buttons",
    description: "Primary button backgrounds",
    keywords: ["button", "submit", "save", "primary"],
  },
  {
    key: "buttonText",
    label: "Primary button text",
    group: "Buttons",
    description: "Text on primary buttons",
    keywords: ["button", "text", "foreground"],
  },
  {
    key: "error",
    label: "Errors",
    group: "Status",
    description: "Error text, validation, failed states",
    keywords: ["error", "danger", "validation", "failed", "status"],
  },
  {
    key: "warning",
    label: "Warnings",
    group: "Status",
    description: "Warning alerts and caution states",
    keywords: ["warning", "caution", "alert", "status"],
  },
  {
    key: "success",
    label: "Success",
    group: "Status",
    description: "Success alerts and completed states",
    keywords: ["success", "complete", "ok", "status"],
  },
  {
    key: "info",
    label: "Info",
    group: "Status",
    description: "Informational alerts and hints",
    keywords: ["info", "notice", "hint", "status"],
  },
  {
    key: "pageBackground",
    label: "Page background",
    group: "Surfaces",
    description: "Main page background",
    keywords: ["background", "surface", "page", "layout"],
  },
  {
    key: "surfaceBackground",
    label: "Panel background",
    group: "Surfaces",
    description: "Cards, panels, elevated surfaces",
    keywords: ["card", "panel", "surface", "container"],
  },
  {
    key: "border",
    label: "Borders",
    group: "Surfaces",
    description: "Card, field, and divider borders",
    keywords: ["border", "divider", "outline", "stroke"],
  },
  {
    key: "headingText",
    label: "Headings",
    group: "Text",
    description: "Page titles and section headings",
    keywords: ["heading", "title", "h1", "h2"],
  },
  {
    key: "text",
    label: "Body text",
    group: "Text",
    description: "Default readable text",
    keywords: ["text", "foreground", "body", "paragraph"],
  },
  {
    key: "textSecondary",
    label: "Secondary text",
    group: "Text",
    description: "Labels, descriptions, supporting text",
    keywords: ["secondary", "label", "description", "caption"],
  },
  {
    key: "textMuted",
    label: "Muted text",
    group: "Text",
    description: "Disabled and low-emphasis text",
    keywords: ["muted", "disabled", "placeholder", "tertiary"],
  },
  {
    key: "codeBackground",
    label: "Code background",
    group: "Code",
    description: "Inline code and code block backgrounds",
    keywords: ["code", "pre", "snippet", "syntax", "background"],
  },
  {
    key: "codeText",
    label: "Code text",
    group: "Code",
    description: "Default text inside code blocks",
    keywords: ["code", "monospace", "snippet", "syntax"],
  },
  {
    key: "codeKeyword",
    label: "Code accent",
    group: "Code",
    description: "Highlighted syntax and code accents",
    keywords: ["code", "keyword", "syntax", "accent"],
  },
  {
    key: "terminalBackground",
    label: "Terminal background",
    group: "Terminal",
    description: "Log and terminal-style output backgrounds",
    keywords: ["terminal", "logs", "console", "debug", "background"],
  },
  {
    key: "terminalText",
    label: "Terminal text",
    group: "Terminal",
    description: "Log and terminal output text",
    keywords: ["terminal", "logs", "console", "debug", "text"],
  },
  {
    key: "terminalPrompt",
    label: "Terminal prompt",
    group: "Terminal",
    description: "Prompt and command accents in terminal output",
    keywords: ["terminal", "prompt", "command", "shell", "accent"],
  },
];

function clampValue(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value));
}

function normalizeHexColor(value: string): string | null {
  const trimmed = value.trim();

  if (/^#[0-9a-f]{3}$/i.test(trimmed)) {
    const [red, green, blue] = trimmed.slice(1).split("");
    return `#${red}${red}${green}${green}${blue}${blue}`.toUpperCase();
  }

  if (/^#[0-9a-f]{4}$/i.test(trimmed)) {
    const [red, green, blue, alpha] = trimmed.slice(1).split("");
    return `#${red}${red}${green}${green}${blue}${blue}${alpha}${alpha}`.toUpperCase();
  }

  if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(trimmed)) {
    return trimmed.toUpperCase();
  }

  return null;
}

function channelToHex(value: number): string {
  return clampValue(Math.round(value), 0, 255)
    .toString(16)
    .padStart(2, "0")
    .toUpperCase();
}

function hexToHsla(value: string): HslaColor {
  const normalized = normalizeHexColor(value) ?? DEFAULT_THEME_COLORS.primary;
  const red = Number.parseInt(normalized.slice(1, 3), 16) / 255;
  const green = Number.parseInt(normalized.slice(3, 5), 16) / 255;
  const blue = Number.parseInt(normalized.slice(5, 7), 16) / 255;
  const alpha =
    normalized.length === 9
      ? Number.parseInt(normalized.slice(7, 9), 16) / 255
      : 1;

  const maxChannel = Math.max(red, green, blue);
  const minChannel = Math.min(red, green, blue);
  const channelDelta = maxChannel - minChannel;
  let hue = 0;

  if (channelDelta !== 0) {
    if (maxChannel === red) {
      hue = 60 * (((green - blue) / channelDelta) % 6);
    } else if (maxChannel === green) {
      hue = 60 * ((blue - red) / channelDelta + 2);
    } else {
      hue = 60 * ((red - green) / channelDelta + 4);
    }
  }

  const lightness = (maxChannel + minChannel) / 2;
  const saturation =
    channelDelta === 0 ? 0 : channelDelta / (1 - Math.abs(2 * lightness - 1));

  return {
    hue: Math.round((hue + 360) % 360),
    saturation: Math.round(saturation * 100),
    lightness: Math.round(lightness * 100),
    alpha: Math.round(alpha * 100) / 100,
  };
}

function hslaToHex(color: HslaColor): string {
  const hue = ((color.hue % 360) + 360) % 360;
  const saturation = clampValue(color.saturation, 0, 100) / 100;
  const lightness = clampValue(color.lightness, 0, 100) / 100;
  const alpha = clampValue(color.alpha, 0, 1);
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const huePrime = hue / 60;
  const secondComponent = chroma * (1 - Math.abs((huePrime % 2) - 1));
  let redPrime = 0;
  let greenPrime = 0;
  let bluePrime = 0;

  if (huePrime >= 0 && huePrime < 1) {
    redPrime = chroma;
    greenPrime = secondComponent;
  } else if (huePrime >= 1 && huePrime < 2) {
    redPrime = secondComponent;
    greenPrime = chroma;
  } else if (huePrime >= 2 && huePrime < 3) {
    greenPrime = chroma;
    bluePrime = secondComponent;
  } else if (huePrime >= 3 && huePrime < 4) {
    greenPrime = secondComponent;
    bluePrime = chroma;
  } else if (huePrime >= 4 && huePrime < 5) {
    redPrime = secondComponent;
    bluePrime = chroma;
  } else {
    redPrime = chroma;
    bluePrime = secondComponent;
  }

  const lightnessOffset = lightness - chroma / 2;
  const red = (redPrime + lightnessOffset) * 255;
  const green = (greenPrime + lightnessOffset) * 255;
  const blue = (bluePrime + lightnessOffset) * 255;
  const alphaHex = alpha < 1 ? channelToHex(Math.round(alpha * 255)) : "";

  return `#${channelToHex(red)}${channelToHex(green)}${channelToHex(
    blue,
  )}${alphaHex}`;
}

function getSliderNumber(value: number | number[] | null): number {
  if (Array.isArray(value)) return value[0] ?? 0;
  return value ?? 0;
}

function getHslColor({ hue, saturation, lightness }: HslaColor): string {
  return `hsl(${Math.round(hue)}, ${Math.round(saturation)}%, ${Math.round(
    lightness,
  )}%)`;
}

const HUE_RANGE_TRACK =
  "linear-gradient(to right, #ff0000, #ffff00 17%, #00ff00 33%, #00ffff 50%, #0000ff 67%, #ff00ff 83%, #ff0000)";

function getSaturationRangeTrack(color: HslaColor): string {
  return `linear-gradient(to right, hsl(${Math.round(
    color.hue,
  )}, 0%, ${Math.round(color.lightness)}%), hsl(${Math.round(
    color.hue,
  )}, 100%, ${Math.round(color.lightness)}%))`;
}

function getLightnessRangeTrack(color: HslaColor): string {
  return `linear-gradient(to right, #000000, hsl(${Math.round(
    color.hue,
  )}, ${Math.round(color.saturation)}%, 50%), #ffffff)`;
}

function getAlphaRangeTrack(color: HslaColor): string {
  return `linear-gradient(to right, transparent, ${getHslColor({
    ...color,
    alpha: 1,
  })})`;
}

function ColorRangeControl({
  label,
  value,
  min,
  max,
  suffix,
  track,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  track: string;
  onChange: (value: number) => void;
}) {
  const handleChange = (nextValue: number | number[] | null) => {
    onChange(clampValue(getSliderNumber(nextValue), min, max));
  };

  return (
    <div
      className={styles.themeRangeControl}
      style={{ "--theme-range-track": track } as CSSProperties}
    >
      <label className={styles.themeRangeHeader}>
        <span>{label}</span>
        <InputNumber
          min={min}
          max={max}
          value={value}
          addonAfter={suffix}
          onChange={(nextValue) =>
            onChange(clampValue(Number(nextValue ?? 0), min, max))
          }
        />
      </label>
      <Slider min={min} max={max} value={value} onChange={handleChange} />
    </div>
  );
}

function getImportedColors(
  value: Partial<Record<ThemeColorKey, string>>,
): ThemeColors | null {
  const nextColors = { ...DEFAULT_THEME_COLORS };
  let foundColor = false;

  for (const target of COLOR_TARGETS) {
    const normalized = normalizeHexColor(value[target.key] ?? "");
    if (!normalized) continue;
    nextColors[target.key] = normalized;
    foundColor = true;
  }

  return foundColor ? nextColors : null;
}

function areThemeColorMapsEqual(
  firstColors: ThemeColors,
  secondColors: ThemeColors,
): boolean {
  return COLOR_TARGETS.every(
    (target) => firstColors[target.key] === secondColors[target.key],
  );
}

function ColorWheel({
  value,
  onChange,
}: {
  value: HslaColor;
  onChange: (value: HslaColor) => void;
}) {
  const wheelRef = useRef<HTMLDivElement>(null);

  const updateFromPointer = (clientX: number, clientY: number) => {
    const rect = wheelRef.current?.getBoundingClientRect();
    if (!rect) return;

    const radius = rect.width / 2;
    const centerX = rect.left + radius;
    const centerY = rect.top + radius;
    const offsetX = clientX - centerX;
    const offsetY = clientY - centerY;
    const distance = Math.sqrt(offsetX * offsetX + offsetY * offsetY);
    const hue = (Math.atan2(offsetY, offsetX) * 180) / Math.PI;
    const saturation = Math.round(
      clampValue((distance / radius) * 100, 0, 100),
    );
    const lightness =
      value.lightness >= 98 || value.lightness <= 2 ? 50 : value.lightness;

    onChange({
      ...value,
      hue: Math.round((hue + 360) % 360),
      saturation,
      lightness,
    });
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    updateFromPointer(event.clientX, event.clientY);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.buttons !== 1) return;
    updateFromPointer(event.clientX, event.clientY);
  };

  const thumbDistance = (value.saturation / 100) * 50;
  const hueRadians = (value.hue * Math.PI) / 180;
  const thumbStyle = {
    left: `${50 + Math.cos(hueRadians) * thumbDistance}%`,
    top: `${50 + Math.sin(hueRadians) * thumbDistance}%`,
  };

  return (
    <div
      ref={wheelRef}
      className={styles.themeColorWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
    >
      <span className={styles.themeColorThumb} style={thumbStyle} />
    </div>
  );
}

export function ThemeEditorCard() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    themeColors,
    themePresets,
    activeThemePresetId,
    setThemeColors,
    saveThemeColors,
    saveThemePreset,
    selectThemePreset,
    toggleThemePresetFavorite,
    deleteThemePreset,
    resetThemeColors,
  } = useTheme();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [draftColors, setDraftColors] = useState<ThemeColors>(themeColors);
  const [selectedKey, setSelectedKey] = useState<ThemeColorKey>("primary");
  const [selectedHsla, setSelectedHsla] = useState<HslaColor>(() =>
    hexToHsla(themeColors.primary),
  );
  const [query, setQuery] = useState("");
  const [hexInput, setHexInput] = useState(themeColors.primary);
  const [themeName, setThemeName] = useState("Custom Theme");
  const selectedColorSyncRef = useRef({
    key: "primary" as ThemeColorKey,
    color: normalizeHexColor(themeColors.primary) ?? themeColors.primary,
  });
  const appliedRequestedPresetIdRef = useRef<string | null>(null);
  const requestedPresetId = searchParams.get("preset");

  const activePreset = useMemo(
    () => themePresets.find((preset) => preset.id === activeThemePresetId),
    [activeThemePresetId, themePresets],
  );

  const sortedPresets = useMemo(
    () => sortThemePresets(themePresets),
    [themePresets],
  );

  useEffect(() => {
    if (!requestedPresetId) {
      appliedRequestedPresetIdRef.current = null;
      return;
    }

    if (appliedRequestedPresetIdRef.current === requestedPresetId) return;

    if (!themePresets.some((preset) => preset.id === requestedPresetId)) return;

    appliedRequestedPresetIdRef.current = requestedPresetId;
    if (requestedPresetId !== activeThemePresetId) {
      selectThemePreset(requestedPresetId);
    }
  }, [activeThemePresetId, requestedPresetId, selectThemePreset, themePresets]);

  useEffect(() => {
    setDraftColors((previousColors) =>
      areThemeColorMapsEqual(previousColors, themeColors)
        ? previousColors
        : themeColors,
    );
  }, [themeColors]);

  useEffect(() => {
    setThemeName(activePreset?.name ?? "Custom Theme");
  }, [activePreset?.id, activePreset?.name]);

  useEffect(() => {
    const nextColor =
      normalizeHexColor(draftColors[selectedKey]) ??
      DEFAULT_THEME_COLORS[selectedKey];

    setHexInput(nextColor);
    setSelectedHsla((previousHsla) => {
      const previousSync = selectedColorSyncRef.current;
      const selectedKeyChanged = previousSync.key !== selectedKey;
      const selectedColorChanged = previousSync.color !== nextColor;
      const previousHslaColor = normalizeHexColor(hslaToHex(previousHsla));

      selectedColorSyncRef.current = {
        key: selectedKey,
        color: nextColor,
      };

      if (
        selectedKeyChanged ||
        (selectedColorChanged && previousHslaColor !== nextColor)
      ) {
        return hexToHsla(nextColor);
      }

      return previousHsla;
    });
  }, [draftColors, selectedKey]);

  const filteredTargets = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return COLOR_TARGETS;

    return COLOR_TARGETS.filter((target) => {
      const haystack = [
        target.label,
        target.group,
        target.description,
        ...target.keywords,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [query]);

  const selectedTarget =
    COLOR_TARGETS.find((target) => target.key === selectedKey) ??
    COLOR_TARGETS[0];
  const hueValue = Math.round(selectedHsla.hue);
  const saturationValue = Math.round(selectedHsla.saturation);
  const lightnessValue = Math.round(selectedHsla.lightness);
  const alphaValue = Math.round(selectedHsla.alpha * 100);

  const updatePresetParam = (presetId: string | null) => {
    const nextSearchParams = new URLSearchParams(searchParams);
    nextSearchParams.set("tab", "theme");
    if (presetId) {
      nextSearchParams.set("preset", presetId);
    } else {
      nextSearchParams.delete("preset");
    }
    setSearchParams(nextSearchParams, { replace: true });
  };

  const updateDraftColors = (nextColors: ThemeColors) => {
    setDraftColors(nextColors);
    setThemeColors(nextColors);
  };

  const updateSelectedColor = (color: string) => {
    const normalizedColor = normalizeHexColor(color) ?? color;
    if (draftColors[selectedKey] === normalizedColor) return;
    updateDraftColors({ ...draftColors, [selectedKey]: normalizedColor });
  };

  const updateSelectedHsla = (patch: Partial<HslaColor>) => {
    const nextHsla = { ...selectedHsla, ...patch };
    setSelectedHsla(nextHsla);
    updateSelectedColor(hslaToHex(nextHsla));
  };

  const handleHexChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextValue = event.target.value;
    setHexInput(nextValue);
    const normalized = normalizeHexColor(nextValue);
    if (normalized) updateSelectedColor(normalized);
  };

  const handleSelectPreset = (presetId: string) => {
    selectThemePreset(presetId);
    updatePresetParam(presetId);
  };

  const handleSave = () => {
    if (isBuiltInThemePreset(activePreset)) {
      const presetId = saveThemePreset(
        themeName === activePreset?.name ? "Custom Theme" : themeName,
        draftColors,
      );
      updatePresetParam(presetId);
    } else {
      saveThemeColors(draftColors, themeName);
    }
    message.success(t("themeEditor.saveSuccess", "Theme colors saved"));
  };

  const handleSaveAs = () => {
    const presetId = saveThemePreset(themeName, draftColors);
    updatePresetParam(presetId);
    message.success(
      t("themeEditor.saveAsSuccess", "Theme saved as a new loadout"),
    );
  };

  const handleReset = () => {
    resetThemeColors();
    updatePresetParam(null);
    message.success(t("themeEditor.resetSuccess", "Theme colors reset"));
  };

  const handleDeletePreset = (presetId: string) => {
    deleteThemePreset(presetId);
    if (presetId === activeThemePresetId) updatePresetParam(null);
    message.success(t("themeEditor.deleteSuccess", "Theme loadout deleted"));
  };

  const handleExport = () => {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            version: 3,
            name: themeName,
            colors: draftColors,
            preset: activePreset,
            exportedAt: new Date().toISOString(),
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${themeName.trim() || "qwenpaw-theme"}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const payload = JSON.parse(await file.text()) as {
        name?: string;
        colors?: Partial<Record<ThemeColorKey, string>>;
        preset?: {
          name?: string;
          colors?: Partial<Record<ThemeColorKey, string>>;
        };
      } & Partial<Record<ThemeColorKey, string>>;
      const imported = payload.colors ?? payload.preset?.colors ?? payload;
      const importedColors = getImportedColors(imported);

      if (!importedColors) {
        throw new Error("No supported colors found");
      }

      const importedName =
        payload.name ??
        payload.preset?.name ??
        file.name.replace(/\.json$/i, "") ??
        "Imported Theme";
      const presetId = saveThemePreset(importedName, importedColors);
      updatePresetParam(presetId);
      message.success(t("themeEditor.importSuccess", "Theme imported"));
    } catch {
      message.error(t("themeEditor.importFailed", "Failed to import theme"));
    } finally {
      event.target.value = "";
    }
  };

  return (
    <Card
      className={styles.formCard}
      title={t("themeEditor.title", "Theme Customization")}
      extra={
        <div className={styles.themeToolbar}>
          <Button
            className={styles.themeToolbarResetButton}
            icon={<RotateCcw size={15} />}
            onClick={handleReset}
          >
            {t("common.reset")}
          </Button>
          <Button
            className={styles.themeToolbarActionButton}
            type="primary"
            icon={<Upload size={15} />}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("themeEditor.import", "Import")}
          </Button>
          <Button
            className={styles.themeToolbarActionButton}
            type="primary"
            icon={<Download size={15} />}
            onClick={handleExport}
          >
            {t("themeEditor.export", "Export")}
          </Button>
          <Button
            className={styles.themeToolbarActionButton}
            type="primary"
            icon={<Plus size={15} />}
            onClick={handleSaveAs}
          >
            {t("themeEditor.saveAs", "Save as new")}
          </Button>
          <Button
            className={styles.themeToolbarActionButton}
            type="primary"
            icon={<Save size={15} />}
            onClick={handleSave}
          >
            {t("common.save")}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className={styles.themeImportInput}
            hidden
            onChange={handleImport}
          />
        </div>
      }
    >
      <div className={styles.themeEditorLayout}>
        <aside className={styles.themeTargetPane}>
          <div className={styles.themeSectionTitle}>
            {t("themeEditor.currentTheme", "Current theme")}
          </div>
          <Input
            value={themeName}
            placeholder={t("themeEditor.themeNamePlaceholder", "Theme name")}
            onChange={(event) => setThemeName(event.target.value)}
          />
          <div className={styles.themeSectionTitle}>
            {t("themeEditor.savedThemes", "Saved themes")}
          </div>
          <div className={styles.themePresetList}>
            {sortedPresets.map((preset) => {
              const active = preset.id === activeThemePresetId;
              const isDefault = isBuiltInThemePreset(preset);
              return (
                <button
                  key={preset.id}
                  type="button"
                  className={`${styles.themePresetButton} ${
                    active ? styles.themePresetButtonActive : ""
                  }`}
                  onClick={() => handleSelectPreset(preset.id)}
                >
                  <span
                    className={styles.themePresetSwatch}
                    style={
                      {
                        "--theme-preset-gradient": getThemePresetGradient(
                          preset.colors,
                        ),
                      } as CSSProperties
                    }
                  />
                  <span className={styles.themePresetName}>{preset.name}</span>
                  {active && (
                    <Check size={14} className={styles.themePresetCheck} />
                  )}
                  <span
                    role="button"
                    tabIndex={0}
                    className={`${styles.themePresetIconButton} ${
                      preset.favorite ? styles.themePresetIconButtonActive : ""
                    }`}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleThemePresetFavorite(preset.id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      event.stopPropagation();
                      toggleThemePresetFavorite(preset.id);
                    }}
                    aria-label={t("themeEditor.favorite", "Favorite")}
                  >
                    <Star
                      size={14}
                      fill={preset.favorite ? "currentColor" : "none"}
                    />
                  </span>
                  {!isDefault && (
                    <span
                      role="button"
                      tabIndex={0}
                      className={styles.themePresetIconButton}
                      onClick={(event) => {
                        event.stopPropagation();
                        handleDeletePreset(preset.id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        event.stopPropagation();
                        handleDeletePreset(preset.id);
                      }}
                      aria-label={t("common.delete")}
                    >
                      <Trash2 size={14} />
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className={styles.themeSectionTitle}>
            {t("themeEditor.palette", "Palette")}
          </div>
          <Input
            value={query}
            placeholder={t("themeEditor.searchPlaceholder", "Search colors")}
            allowClear
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className={styles.themeTargetList}>
            {filteredTargets.map((target) => {
              const active = target.key === selectedKey;
              return (
                <button
                  key={target.key}
                  type="button"
                  className={`${styles.themeTargetButton} ${
                    active ? styles.themeTargetButtonActive : ""
                  }`}
                  onClick={() => setSelectedKey(target.key)}
                >
                  <span
                    className={styles.themeTargetSwatch}
                    style={{ background: draftColors[target.key] }}
                  />
                  <span className={styles.themeTargetMeta}>
                    <span className={styles.themeTargetName}>
                      {target.label}
                    </span>
                    <span className={styles.themeTargetGroup}>
                      {target.group}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <div className={styles.themeWorkspace}>
          <section className={styles.themePickerPane}>
            <div className={styles.themeSelectedHeader}>
              <span
                className={styles.themeSelectedSwatch}
                style={{ background: draftColors[selectedKey] }}
              />
              <div>
                <div className={styles.themeSelectedName}>
                  {selectedTarget.label}
                </div>
                <div className={styles.themeSelectedDescription}>
                  {selectedTarget.description}
                </div>
              </div>
            </div>

            <div className={styles.themePickerGrid}>
              <ColorWheel value={selectedHsla} onChange={updateSelectedHsla} />
              <div className={styles.themeControls}>
                <ColorRangeControl
                  label="H"
                  min={0}
                  max={360}
                  value={hueValue}
                  track={HUE_RANGE_TRACK}
                  onChange={(value) => updateSelectedHsla({ hue: value })}
                />
                <ColorRangeControl
                  label="S"
                  min={0}
                  max={100}
                  value={saturationValue}
                  suffix="%"
                  track={getSaturationRangeTrack(selectedHsla)}
                  onChange={(value) =>
                    updateSelectedHsla({ saturation: value })
                  }
                />
                <ColorRangeControl
                  label="L"
                  min={0}
                  max={100}
                  value={lightnessValue}
                  suffix="%"
                  track={getLightnessRangeTrack(selectedHsla)}
                  onChange={(value) => updateSelectedHsla({ lightness: value })}
                />
                <label className={styles.themeHexControl}>
                  <span>HEX</span>
                  <Input value={hexInput} onChange={handleHexChange} />
                </label>
                <ColorRangeControl
                  label="Alpha"
                  min={0}
                  max={100}
                  value={alphaValue}
                  suffix="%"
                  track={getAlphaRangeTrack(selectedHsla)}
                  onChange={(value) =>
                    updateSelectedHsla({ alpha: value / 100 })
                  }
                />
              </div>
            </div>
          </section>

          <section className={styles.themePreviewPane}>
            <div className={styles.themePreviewTitle}>
              {t("themeEditor.preview", "Preview")}
            </div>
            <div className={styles.themePreviewGrid}>
              <div className={styles.themePreviewSampleBlock}>
                <div className={styles.themePreviewHeading}>
                  Workspace heading
                </div>
                <div className={styles.themePreviewBody}>
                  Readable body text
                </div>
                <div className={styles.themePreviewSecondary}>
                  Secondary description text
                </div>
                <a className={styles.themePreviewLink} href="#theme-preview">
                  {t("themeEditor.link", "Sample link")}
                </a>
              </div>
              <div className={styles.themePreviewSampleBlock}>
                <button
                  type="button"
                  className={styles.themePreviewPrimaryButton}
                >
                  {t("themeEditor.primaryButton", "Primary Button")}
                </button>
                <button
                  type="button"
                  className={styles.themePreviewDefaultButton}
                >
                  {t("themeEditor.defaultButton", "Default Button")}
                </button>
              </div>
              <div className={styles.themePreviewStatusGrid}>
                <div
                  className={`${styles.themePreviewStatus} ${styles.themePreviewError}`}
                >
                  {t("themeEditor.error", "Error message")}
                </div>
                <div
                  className={`${styles.themePreviewStatus} ${styles.themePreviewWarning}`}
                >
                  {t("themeEditor.warning", "Warning message")}
                </div>
                <div
                  className={`${styles.themePreviewStatus} ${styles.themePreviewSuccess}`}
                >
                  {t("themeEditor.success", "Success message")}
                </div>
              </div>
              <div className={styles.themePreviewCodeStack}>
                <pre className={styles.themePreviewCode}>
                  <code>
                    <span className={styles.themePreviewCodeKeyword}>
                      const
                    </span>{" "}
                    theme = "QwenPaw";
                  </code>
                </pre>
                <div className={styles.themePreviewTerminal}>
                  <span className={styles.themePreviewTerminalPrompt}>$</span>{" "}
                  qwenpaw app
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </Card>
  );
}
