import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";

export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export interface ThemeColors {
  primary: string;
  buttonBackground: string;
  buttonText: string;
  link: string;
  error: string;
  warning: string;
  success: string;
  info: string;
  pageBackground: string;
  surfaceBackground: string;
  border: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  headingText: string;
  codeBackground: string;
  codeText: string;
  codeKeyword: string;
  terminalBackground: string;
  terminalText: string;
  terminalPrompt: string;
}

export type ThemeColorKey = keyof ThemeColors;

export interface ThemePreset {
  id: string;
  name: string;
  colors: ThemeColors;
  favorite: boolean;
  appearance?: ResolvedTheme;
  builtIn?: boolean;
  createdAt: string;
  updatedAt: string;
}

export const DEFAULT_THEME_COLORS: ThemeColors = {
  primary: "#FF7F16",
  buttonBackground: "#FF7F16",
  buttonText: "#FFFFFF",
  link: "#FF7F16",
  error: "#FF4D4F",
  warning: "#FAAD14",
  success: "#52C41A",
  info: "#1677FF",
  pageBackground: "#F9F8F4",
  surfaceBackground: "#FFFFFF",
  border: "#ECE9E4",
  text: "#1A1A1A",
  textSecondary: "#595959",
  textMuted: "#8C8C8C",
  headingText: "#101010",
  codeBackground: "#F5F5F5",
  codeText: "#3B3B3B",
  codeKeyword: "#C41D7F",
  terminalBackground: "#111111",
  terminalText: "#E6E6E6",
  terminalPrompt: "#52C41A",
};

export const DEFAULT_DARK_THEME_COLORS: ThemeColors = {
  primary: "#FF7F16",
  buttonBackground: "#FF7F16",
  buttonText: "#FFFFFF",
  link: "#FF7F16",
  error: "#FF4D4F",
  warning: "#FAAD14",
  success: "#52C41A",
  info: "#1677FF",
  pageBackground: "#141414",
  surfaceBackground: "#1F1F1F",
  border: "#343434",
  text: "#D9D9D9",
  textSecondary: "#A6A6A6",
  textMuted: "#737373",
  headingText: "#FFFFFF",
  codeBackground: "#2A2A2A",
  codeText: "#E6E6E6",
  codeKeyword: "#FF85C0",
  terminalBackground: "#0E0E0E",
  terminalText: "#E6E6E6",
  terminalPrompt: "#52C41A",
};

const STORAGE_KEY = "qwenpaw-theme";
const CUSTOM_STORAGE_KEY = "qwenpaw-theme-customization";
export const DEFAULT_LIGHT_THEME_PRESET_ID = "qwenpaw-default-light";
export const DEFAULT_DARK_THEME_PRESET_ID = "qwenpaw-default-dark";
const DEFAULT_THEME_PRESET_ID = DEFAULT_LIGHT_THEME_PRESET_ID;
const LEGACY_DEFAULT_THEME_PRESET_ID = "qwenpaw-default";
const MIGRATED_THEME_PRESET_ID = "qwenpaw-custom";
const THEME_COLOR_KEYS = Object.keys(DEFAULT_THEME_COLORS) as ThemeColorKey[];
const THEME_PRESET_GRADIENT_KEYS: ThemeColorKey[] = [
  "pageBackground",
  "surfaceBackground",
  "primary",
  "buttonBackground",
  "link",
  "text",
];

export function getThemePresetGradient(colors: ThemeColors): string {
  const gradientColors = THEME_PRESET_GRADIENT_KEYS.reduce<string[]>(
    (acc, key) => {
      const color = colors[key];
      if (!acc.includes(color)) acc.push(color);
      return acc;
    },
    [],
  ).slice(0, 4);

  if (gradientColors.length <= 1) return gradientColors[0] ?? colors.primary;

  const stops = gradientColors.map((color, index) => {
    const position = Math.round((index / (gradientColors.length - 1)) * 100);
    return `${color} ${position}%`;
  });

  return `linear-gradient(135deg, ${stops.join(", ")})`;
}

const BUILT_IN_THEME_PRESETS: ThemePreset[] = [
  {
    id: DEFAULT_LIGHT_THEME_PRESET_ID,
    name: "light",
    colors: DEFAULT_THEME_COLORS,
    favorite: true,
    appearance: "light",
    builtIn: true,
    createdAt: "built-in",
    updatedAt: "built-in",
  },
  {
    id: "qwenpaw-porcelain-light",
    name: "porcelain",
    colors: {
      primary: "#2F6FED",
      buttonBackground: "#2F6FED",
      buttonText: "#FFFFFF",
      link: "#1D4ED8",
      error: "#DC2626",
      warning: "#B7791F",
      success: "#0F8B62",
      info: "#2563EB",
      pageBackground: "#F4F7FA",
      surfaceBackground: "#FFFFFF",
      border: "#DCE4EE",
      text: "#172033",
      textSecondary: "#526070",
      textMuted: "#8793A3",
      headingText: "#0D1526",
      codeBackground: "#EEF3F8",
      codeText: "#27364A",
      codeKeyword: "#8B3FA8",
      terminalBackground: "#111827",
      terminalText: "#E5E7EB",
      terminalPrompt: "#38BDF8",
    },
    favorite: false,
    appearance: "light",
    builtIn: true,
    createdAt: "built-in",
    updatedAt: "built-in",
  },
  {
    id: "qwenpaw-paper-light",
    name: "paper",
    colors: {
      primary: "#B85C38",
      buttonBackground: "#B85C38",
      buttonText: "#FFFFFF",
      link: "#9A4B2F",
      error: "#C2413D",
      warning: "#A16207",
      success: "#3F7A42",
      info: "#2E6F95",
      pageBackground: "#F7F1E7",
      surfaceBackground: "#FFFCF6",
      border: "#E4D7C5",
      text: "#2E261F",
      textSecondary: "#6A5C50",
      textMuted: "#9A8C7A",
      headingText: "#241A13",
      codeBackground: "#F0E6D7",
      codeText: "#3B3027",
      codeKeyword: "#7C3AED",
      terminalBackground: "#1D1712",
      terminalText: "#F5EBDD",
      terminalPrompt: "#F59E0B",
    },
    favorite: false,
    appearance: "light",
    builtIn: true,
    createdAt: "built-in",
    updatedAt: "built-in",
  },
  {
    id: DEFAULT_DARK_THEME_PRESET_ID,
    name: "dark",
    colors: DEFAULT_DARK_THEME_COLORS,
    favorite: true,
    appearance: "dark",
    builtIn: true,
    createdAt: "built-in",
    updatedAt: "built-in",
  },
  {
    id: "qwenpaw-graphite-dark",
    name: "graphite",
    colors: {
      primary: "#2DD4BF",
      buttonBackground: "#14B8A6",
      buttonText: "#061413",
      link: "#5EEAD4",
      error: "#FB7185",
      warning: "#FBBF24",
      success: "#34D399",
      info: "#60A5FA",
      pageBackground: "#111315",
      surfaceBackground: "#1B1F22",
      border: "#30363A",
      text: "#E4E7EA",
      textSecondary: "#AAB2B9",
      textMuted: "#78828A",
      headingText: "#F7F8F9",
      codeBackground: "#242A2E",
      codeText: "#DDE5EA",
      codeKeyword: "#C084FC",
      terminalBackground: "#090B0C",
      terminalText: "#D8F3EF",
      terminalPrompt: "#2DD4BF",
    },
    favorite: false,
    appearance: "dark",
    builtIn: true,
    createdAt: "built-in",
    updatedAt: "built-in",
  },
  {
    id: "qwenpaw-ember-dark",
    name: "ember",
    colors: {
      primary: "#FF8A3D",
      buttonBackground: "#E86F26",
      buttonText: "#FFF8F2",
      link: "#FFB470",
      error: "#FF6B6B",
      warning: "#F7B955",
      success: "#78D08A",
      info: "#7CC7FF",
      pageBackground: "#15110F",
      surfaceBackground: "#221B17",
      border: "#3A2D26",
      text: "#F1E7DE",
      textSecondary: "#C7B6A8",
      textMuted: "#8E7D70",
      headingText: "#FFF8F2",
      codeBackground: "#2D241F",
      codeText: "#F4DED1",
      codeKeyword: "#FF9AC1",
      terminalBackground: "#0F0B09",
      terminalText: "#F4DED1",
      terminalPrompt: "#FFB470",
    },
    favorite: false,
    appearance: "dark",
    builtIn: true,
    createdAt: "built-in",
    updatedAt: "built-in",
  },
];

const BUILT_IN_THEME_PRESET_IDS = new Set(
  BUILT_IN_THEME_PRESETS.map((preset) => preset.id),
);

interface ThemeLibraryState {
  activePresetId: string;
  colors: ThemeColors;
  presets: ThemePreset[];
}

interface ThemeContextValue {
  /** User selected preference: light / dark / system */
  themeMode: ThemeMode;
  /** Resolved final theme after applying system preference */
  isDark: boolean;
  setThemeMode: (mode: ThemeMode) => void;
  /** Convenience toggle: light ↔ dark (skips system) */
  toggleTheme: () => void;
  themeColors: ThemeColors;
  themePresets: ThemePreset[];
  activeThemePresetId: string;
  setThemeColors: (colors: Partial<ThemeColors>) => void;
  saveThemeColors: (colors?: ThemeColors, name?: string) => void;
  saveThemePreset: (name: string, colors?: ThemeColors) => string;
  selectThemePreset: (presetId: string) => void;
  toggleThemePresetFavorite: (presetId: string) => void;
  deleteThemePreset: (presetId: string) => void;
  resetThemeColors: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  themeMode: "light",
  isDark: false,
  setThemeMode: () => {},
  toggleTheme: () => {},
  themeColors: DEFAULT_THEME_COLORS,
  themePresets: [],
  activeThemePresetId: DEFAULT_THEME_PRESET_ID,
  setThemeColors: () => {},
  saveThemeColors: () => {},
  saveThemePreset: () => DEFAULT_THEME_PRESET_ID,
  selectThemePreset: () => {},
  toggleThemePresetFavorite: () => {},
  deleteThemePreset: () => {},
  resetThemeColors: () => {},
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeHexColor(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(trimmed)) {
    return trimmed.toUpperCase();
  }
  return null;
}

function sanitizeThemeColors(colors: Partial<ThemeColors>): ThemeColors {
  return THEME_COLOR_KEYS.reduce((acc, colorKey) => {
    const normalized = normalizeHexColor(colors[colorKey]);
    acc[colorKey] = normalized ?? DEFAULT_THEME_COLORS[colorKey];
    return acc;
  }, {} as ThemeColors);
}

function areThemeColorsEqual(first: ThemeColors, second: ThemeColors): boolean {
  return THEME_COLOR_KEYS.every(
    (colorKey) => first[colorKey] === second[colorKey],
  );
}

function hasThemeColorInput(value: unknown): value is Partial<ThemeColors> {
  if (!isRecord(value)) return false;
  return THEME_COLOR_KEYS.some(
    (colorKey) => normalizeHexColor(value[colorKey]) !== null,
  );
}

function createThemePresetId(): string {
  return `theme-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function cloneThemePreset(preset: ThemePreset): ThemePreset {
  return {
    ...preset,
    colors: { ...preset.colors },
  };
}

function getDefaultThemePreset(isDark = false): ThemePreset {
  const defaultPresetId = isDark
    ? DEFAULT_DARK_THEME_PRESET_ID
    : DEFAULT_LIGHT_THEME_PRESET_ID;
  const preset = BUILT_IN_THEME_PRESETS.find(
    (item) => item.id === defaultPresetId,
  );
  return cloneThemePreset(preset ?? BUILT_IN_THEME_PRESETS[0]);
}

export function isBuiltInThemePreset(preset?: ThemePreset | null): boolean {
  return Boolean(
    preset &&
      (preset.builtIn ||
        preset.createdAt === "default" ||
        preset.createdAt === "built-in" ||
        BUILT_IN_THEME_PRESET_IDS.has(preset.id) ||
        preset.id === LEGACY_DEFAULT_THEME_PRESET_ID),
  );
}

function getBuiltInThemePresetOrder(preset: ThemePreset): number {
  const index = BUILT_IN_THEME_PRESETS.findIndex(
    (item) => item.id === preset.id,
  );
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function sortThemePresets(presets: ThemePreset[]): ThemePreset[] {
  return [...presets].sort((firstPreset, secondPreset) => {
    const firstIsBuiltIn = isBuiltInThemePreset(firstPreset);
    const secondIsBuiltIn = isBuiltInThemePreset(secondPreset);

    if (firstIsBuiltIn || secondIsBuiltIn) {
      if (firstIsBuiltIn && secondIsBuiltIn) {
        return (
          getBuiltInThemePresetOrder(firstPreset) -
          getBuiltInThemePresetOrder(secondPreset)
        );
      }
      return firstIsBuiltIn ? -1 : 1;
    }

    if (firstPreset.favorite !== secondPreset.favorite) {
      return firstPreset.favorite ? -1 : 1;
    }

    return secondPreset.updatedAt.localeCompare(firstPreset.updatedAt);
  });
}

function sanitizePreset(value: unknown, index: number): ThemePreset | null {
  if (!isRecord(value) || !hasThemeColorInput(value.colors)) return null;

  const id =
    typeof value.id === "string" && value.id.trim()
      ? value.id.trim()
      : `theme-imported-${index}`;
  const builtInPreset = BUILT_IN_THEME_PRESETS.find(
    (preset) => preset.id === id,
  );
  const fallbackName = builtInPreset?.name ?? "Custom Theme";
  const name =
    typeof value.name === "string" && value.name.trim()
      ? value.name.trim()
      : fallbackName;
  const now = new Date().toISOString();
  const appearance =
    value.appearance === "light" || value.appearance === "dark"
      ? value.appearance
      : undefined;

  return {
    id,
    name,
    colors: sanitizeThemeColors(value.colors),
    favorite: Boolean(value.favorite),
    appearance,
    builtIn: BUILT_IN_THEME_PRESET_IDS.has(id),
    createdAt: typeof value.createdAt === "string" ? value.createdAt : now,
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : now,
  };
}

function normalizePresetName(name: string | undefined): string {
  return name?.trim() || "Custom Theme";
}

function ensureBuiltInPresets(presets: ThemePreset[]): ThemePreset[] {
  const legacyDefaultPreset = presets.find(
    (preset) => preset.id === LEGACY_DEFAULT_THEME_PRESET_ID,
  );
  const builtInPresets = BUILT_IN_THEME_PRESETS.map((preset) => {
    const storedPreset = presets.find((item) => item.id === preset.id);
    return {
      ...cloneThemePreset(preset),
      favorite:
        storedPreset?.favorite ??
        (preset.id === DEFAULT_LIGHT_THEME_PRESET_ID ||
        preset.id === DEFAULT_DARK_THEME_PRESET_ID
          ? legacyDefaultPreset?.favorite ?? preset.favorite
          : preset.favorite),
    };
  });
  const customPresets = presets.filter(
    (preset) =>
      !BUILT_IN_THEME_PRESET_IDS.has(preset.id) &&
      preset.id !== LEGACY_DEFAULT_THEME_PRESET_ID,
  );
  return [...builtInPresets, ...customPresets];
}

function persistThemeLibrary(library: ThemeLibraryState) {
  try {
    localStorage.setItem(
      CUSTOM_STORAGE_KEY,
      JSON.stringify({
        version: 3,
        activePresetId: library.activePresetId,
        colors: library.colors,
        presets: library.presets,
      }),
    );
  } catch {
    // ignore storage errors
  }
}

function getInitialThemeLibrary(isDark: boolean): ThemeLibraryState {
  const defaultPreset = getDefaultThemePreset(isDark);
  const fallback = {
    activePresetId: defaultPreset.id,
    colors: defaultPreset.colors,
    presets: ensureBuiltInPresets([]),
  };

  try {
    const stored = localStorage.getItem(CUSTOM_STORAGE_KEY);
    if (!stored) return fallback;
    const parsed = JSON.parse(stored) as unknown;
    if (!isRecord(parsed)) return fallback;
    const storedVersion =
      typeof parsed.version === "number" ? parsed.version : 1;
    const parsedPresetValue = parsed.presets;
    const hasPresetLibrary = Array.isArray(parsedPresetValue);

    const rawPresets: unknown[] = hasPresetLibrary ? parsedPresetValue : [];
    const parsedPresets = rawPresets
      .map((preset, index) => sanitizePreset(preset, index))
      .filter((preset): preset is ThemePreset => Boolean(preset));
    let presets = ensureBuiltInPresets(parsedPresets);
    let activePresetId =
      typeof parsed.activePresetId === "string"
        ? parsed.activePresetId
        : defaultPreset.id;

    if (activePresetId === LEGACY_DEFAULT_THEME_PRESET_ID) {
      activePresetId = defaultPreset.id;
    }

    const rawColors = hasThemeColorInput(parsed.colors)
      ? parsed.colors
      : hasThemeColorInput(parsed)
      ? parsed
      : null;

    if (
      rawColors &&
      (!hasPresetLibrary || storedVersion < 2) &&
      !presets.some((preset) => preset.id === MIGRATED_THEME_PRESET_ID)
    ) {
      const migratedPreset: ThemePreset = {
        id: MIGRATED_THEME_PRESET_ID,
        name: "Custom Theme",
        colors: sanitizeThemeColors(rawColors),
        favorite: false,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      presets = ensureBuiltInPresets([...presets, migratedPreset]);
      activePresetId = MIGRATED_THEME_PRESET_ID;
    }

    const activePreset =
      presets.find((preset) => preset.id === activePresetId) ?? defaultPreset;
    const colors =
      rawColors && !isBuiltInThemePreset(activePreset)
        ? sanitizeThemeColors(rawColors)
        : activePreset.colors;

    return {
      activePresetId: activePreset.id,
      colors,
      presets,
    };
  } catch {
    return fallback;
  }
}

function getRgbTriplet(color: string): string {
  const normalized = normalizeHexColor(color) ?? "#000000";
  const hex = normalized.slice(1, 7);
  const red = Number.parseInt(hex.slice(0, 2), 16);
  const green = Number.parseInt(hex.slice(2, 4), 16);
  const blue = Number.parseInt(hex.slice(4, 6), 16);
  return `${red}, ${green}, ${blue}`;
}

function applyThemeColorVariables(colors: ThemeColors) {
  const root = document.documentElement;
  root.style.setProperty("--qwenpaw-color-primary", colors.primary);
  root.style.setProperty(
    "--qwenpaw-color-primary-rgb",
    getRgbTriplet(colors.primary),
  );
  root.style.setProperty("--qwenpaw-color-button-bg", colors.buttonBackground);
  root.style.setProperty(
    "--qwenpaw-color-button-bg-rgb",
    getRgbTriplet(colors.buttonBackground),
  );
  root.style.setProperty("--qwenpaw-color-button-text", colors.buttonText);
  root.style.setProperty("--qwenpaw-color-link", colors.link);
  root.style.setProperty("--qwenpaw-color-error", colors.error);
  root.style.setProperty("--qwenpaw-color-warning", colors.warning);
  root.style.setProperty(
    "--qwenpaw-color-warning-rgb",
    getRgbTriplet(colors.warning),
  );
  root.style.setProperty("--qwenpaw-color-success", colors.success);
  root.style.setProperty(
    "--qwenpaw-color-success-rgb",
    getRgbTriplet(colors.success),
  );
  root.style.setProperty("--qwenpaw-color-info", colors.info);
  root.style.setProperty(
    "--qwenpaw-color-info-rgb",
    getRgbTriplet(colors.info),
  );
  root.style.setProperty("--qwenpaw-color-page-bg", colors.pageBackground);
  root.style.setProperty(
    "--qwenpaw-color-surface-bg",
    colors.surfaceBackground,
  );
  root.style.setProperty("--qwenpaw-color-border", colors.border);
  root.style.setProperty("--qwenpaw-color-text", colors.text);
  root.style.setProperty(
    "--qwenpaw-color-text-secondary",
    colors.textSecondary,
  );
  root.style.setProperty("--qwenpaw-color-text-muted", colors.textMuted);
  root.style.setProperty("--qwenpaw-color-heading", colors.headingText);
  root.style.setProperty("--qwenpaw-color-code-bg", colors.codeBackground);
  root.style.setProperty("--qwenpaw-color-code-text", colors.codeText);
  root.style.setProperty("--qwenpaw-color-code-keyword", colors.codeKeyword);
  root.style.setProperty(
    "--qwenpaw-color-terminal-bg",
    colors.terminalBackground,
  );
  root.style.setProperty("--qwenpaw-color-terminal-text", colors.terminalText);
  root.style.setProperty(
    "--qwenpaw-color-terminal-prompt",
    colors.terminalPrompt,
  );
  root.style.setProperty("--colorPrimary", colors.primary);
  root.style.setProperty("--colorErrorText", colors.error);
  root.style.setProperty("--colorWarningText", colors.warning);
}

function getInitialMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // ignore storage errors
  }
  return "system";
}

function resolveIsDark(mode: ThemeMode): boolean {
  if (mode === "dark") return true;
  if (mode === "light") return false;
  // system
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [themeMode, setThemeModeState] = useState<ThemeMode>(getInitialMode);
  const [isDark, setIsDark] = useState<boolean>(() =>
    resolveIsDark(getInitialMode()),
  );
  const [themeLibrary, setThemeLibrary] = useState<ThemeLibraryState>(() =>
    getInitialThemeLibrary(resolveIsDark(getInitialMode())),
  );
  const {
    activePresetId,
    colors: themeColors,
    presets: themePresets,
  } = themeLibrary;

  // Apply dark/light class to <html> element for global CSS variable overrides
  useEffect(() => {
    const html = document.documentElement;
    if (isDark) {
      html.classList.add("dark-mode");
    } else {
      html.classList.remove("dark-mode");
    }
  }, [isDark]);

  useEffect(() => {
    applyThemeColorVariables(themeColors);
  }, [themeColors]);

  useEffect(() => {
    if (
      activePresetId !== DEFAULT_LIGHT_THEME_PRESET_ID &&
      activePresetId !== DEFAULT_DARK_THEME_PRESET_ID &&
      activePresetId !== LEGACY_DEFAULT_THEME_PRESET_ID
    ) {
      return;
    }

    setThemeLibrary((prev) => {
      if (
        prev.activePresetId !== DEFAULT_LIGHT_THEME_PRESET_ID &&
        prev.activePresetId !== DEFAULT_DARK_THEME_PRESET_ID &&
        prev.activePresetId !== LEGACY_DEFAULT_THEME_PRESET_ID
      ) {
        return prev;
      }
      const defaultPreset = getDefaultThemePreset(isDark);
      const nextPresets = ensureBuiltInPresets(prev.presets);
      if (
        prev.activePresetId === defaultPreset.id &&
        areThemeColorsEqual(prev.colors, defaultPreset.colors) &&
        prev.presets.length === nextPresets.length
      ) {
        return prev;
      }
      return {
        ...prev,
        activePresetId: defaultPreset.id,
        colors: defaultPreset.colors,
        presets: nextPresets,
      };
    });
  }, [activePresetId, isDark]);

  // Listen to system theme changes when mode is "system"
  useEffect(() => {
    if (themeMode !== "system") return;

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      setIsDark(e.matches);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [themeMode]);

  const setThemeMode = useCallback((mode: ThemeMode) => {
    setThemeModeState(mode);
    setIsDark(resolveIsDark(mode));
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // ignore
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeMode(isDark ? "light" : "dark");
  }, [isDark, setThemeMode]);

  const setThemeColors = useCallback((colors: Partial<ThemeColors>) => {
    setThemeLibrary((prev) => ({
      ...prev,
      colors: sanitizeThemeColors({ ...prev.colors, ...colors }),
    }));
  }, []);

  const saveThemeColors = useCallback(
    (colors?: ThemeColors, name?: string) => {
      setThemeLibrary((prev) => {
        const nextColors = sanitizeThemeColors(colors ?? prev.colors);
        const currentPreset = prev.presets.find(
          (preset) => preset.id === prev.activePresetId,
        );
        const canUpdateCurrent =
          currentPreset && !isBuiltInThemePreset(currentPreset);
        const now = new Date().toISOString();
        const appearance: ResolvedTheme = isDark ? "dark" : "light";
        let nextActivePresetId = prev.activePresetId;
        let nextPresets: ThemePreset[];

        if (canUpdateCurrent) {
          nextPresets = prev.presets.map((preset) =>
            preset.id === currentPreset.id
              ? {
                  ...preset,
                  name: normalizePresetName(name ?? preset.name),
                  colors: nextColors,
                  appearance,
                  updatedAt: now,
                }
              : preset,
          );
        } else {
          const presetId = createThemePresetId();
          nextActivePresetId = presetId;
          nextPresets = [
            ...prev.presets,
            {
              id: presetId,
              name: normalizePresetName(name),
              colors: nextColors,
              favorite: false,
              appearance,
              createdAt: now,
              updatedAt: now,
            },
          ];
        }

        const nextLibrary = {
          activePresetId: nextActivePresetId,
          colors: nextColors,
          presets: ensureBuiltInPresets(nextPresets),
        };
        persistThemeLibrary(nextLibrary);
        return nextLibrary;
      });
    },
    [isDark],
  );

  const saveThemePreset = useCallback(
    (name: string, colors?: ThemeColors) => {
      const presetId = createThemePresetId();
      setThemeLibrary((prev) => {
        const now = new Date().toISOString();
        const nextColors = sanitizeThemeColors(colors ?? prev.colors);
        const appearance: ResolvedTheme = isDark ? "dark" : "light";
        const nextLibrary = {
          activePresetId: presetId,
          colors: nextColors,
          presets: ensureBuiltInPresets([
            ...prev.presets,
            {
              id: presetId,
              name: normalizePresetName(name),
              colors: nextColors,
              favorite: false,
              appearance,
              createdAt: now,
              updatedAt: now,
            },
          ]),
        };
        persistThemeLibrary(nextLibrary);
        return nextLibrary;
      });
      return presetId;
    },
    [isDark],
  );

  const selectThemePreset = useCallback(
    (presetId: string) => {
      const selectedPreset = themePresets.find((item) => item.id === presetId);
      if (selectedPreset?.appearance) {
        setThemeMode(selectedPreset.appearance);
      }

      setThemeLibrary((prev) => {
        const preset = prev.presets.find((item) => item.id === presetId);
        if (!preset) return prev;
        const nextLibrary = {
          ...prev,
          activePresetId: preset.id,
          colors: preset.colors,
        };
        persistThemeLibrary(nextLibrary);
        return nextLibrary;
      });
    },
    [setThemeMode, themePresets],
  );

  const toggleThemePresetFavorite = useCallback((presetId: string) => {
    setThemeLibrary((prev) => {
      const nextLibrary = {
        ...prev,
        presets: ensureBuiltInPresets(
          prev.presets.map((preset) =>
            preset.id === presetId
              ? { ...preset, favorite: !preset.favorite }
              : preset,
          ),
        ),
      };
      persistThemeLibrary(nextLibrary);
      return nextLibrary;
    });
  }, []);

  const deleteThemePreset = useCallback(
    (presetId: string) => {
      setThemeLibrary((prev) => {
        const presetToDelete = prev.presets.find(
          (preset) => preset.id === presetId,
        );
        if (isBuiltInThemePreset(presetToDelete)) return prev;

        const nextPresets = ensureBuiltInPresets(
          prev.presets.filter((preset) => preset.id !== presetId),
        );
        const defaultPreset =
          nextPresets.find(
            (preset) => preset.id === getDefaultThemePreset(isDark).id,
          ) ?? nextPresets[0];
        const activePreset =
          prev.activePresetId === presetId
            ? defaultPreset
            : nextPresets.find((preset) => preset.id === prev.activePresetId) ??
              defaultPreset;
        const nextLibrary = {
          activePresetId: activePreset.id,
          colors: activePreset.colors,
          presets: nextPresets,
        };
        persistThemeLibrary(nextLibrary);
        return nextLibrary;
      });
    },
    [isDark],
  );

  const resetThemeColors = useCallback(() => {
    setThemeLibrary((prev) => {
      const defaultPreset = getDefaultThemePreset(isDark);
      const nextLibrary = {
        activePresetId: defaultPreset.id,
        colors: defaultPreset.colors,
        presets: ensureBuiltInPresets(prev.presets),
      };
      persistThemeLibrary(nextLibrary);
      return nextLibrary;
    });
  }, [isDark]);

  return (
    <ThemeContext.Provider
      value={{
        themeMode,
        isDark,
        setThemeMode,
        toggleTheme,
        themeColors,
        themePresets,
        activeThemePresetId: activePresetId,
        setThemeColors,
        saveThemeColors,
        saveThemePreset,
        selectThemePreset,
        toggleThemePresetFavorite,
        deleteThemePreset,
        resetThemeColors,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
