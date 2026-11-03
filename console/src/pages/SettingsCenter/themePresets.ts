import type { ThemeConfig } from "@/api/modules/theme";

export interface ThemePreset {
  id: string;
  name: string;
  theme: ThemeConfig;
}

export const THEME_PRESETS: readonly ThemePreset[] = [
  {
    id: "qwenpaw",
    name: "QwenPaw",
    theme: {
      accent: "#ff7f16",
      accent_hover: "#e96f0b",
      accent_bg: "rgba(255, 127, 22, 0.1)",
      dark: {
        accent: "#ff9d4d",
        accent_bg: "rgba(255, 157, 77, 0.16)",
        surface: "#1f1f1f",
      },
    },
  },
  {
    id: "codex",
    name: "Codex",
    theme: {
      accent: "#2563eb",
      accent_hover: "#1d4ed8",
      accent_bg: "rgba(37, 99, 235, 0.1)",
      dark: {
        accent: "#60a5fa",
        accent_bg: "rgba(96, 165, 250, 0.16)",
        surface: "#181818",
      },
    },
  },
  {
    id: "ayu",
    name: "Ayu",
    theme: {
      accent: "#c56a00",
      accent_hover: "#a85700",
      accent_bg: "rgba(197, 106, 0, 0.1)",
      dark: {
        accent: "#ffb454",
        accent_bg: "rgba(255, 180, 84, 0.16)",
        surface: "#17191c",
      },
    },
  },
  {
    id: "catppuccin",
    name: "Catppuccin",
    theme: {
      accent: "#7c3aed",
      accent_hover: "#6d28d9",
      accent_bg: "rgba(124, 58, 237, 0.1)",
      dark: {
        accent: "#c4a7e7",
        accent_bg: "rgba(196, 167, 231, 0.16)",
        surface: "#1e1e2e",
      },
    },
  },
  {
    id: "dracula",
    name: "Dracula",
    theme: {
      accent: "#c0268f",
      accent_hover: "#a21caf",
      accent_bg: "rgba(192, 38, 143, 0.1)",
      dark: {
        accent: "#ff79c6",
        accent_bg: "rgba(255, 121, 198, 0.16)",
        surface: "#282a36",
      },
    },
  },
  {
    id: "everforest",
    name: "Everforest",
    theme: {
      accent: "#2f7d4b",
      accent_hover: "#27673e",
      accent_bg: "rgba(47, 125, 75, 0.1)",
      dark: {
        accent: "#a7c080",
        accent_bg: "rgba(167, 192, 128, 0.16)",
        surface: "#1e2326",
      },
    },
  },
];

export const DEFAULT_THEME_PRESET = THEME_PRESETS[0];

const COLOR_KEYS = ["accent", "accent_hover", "accent_bg"] as const;
const DARK_COLOR_KEYS = ["accent", "accent_bg", "surface"] as const;

function hasCustomColors(theme: ThemeConfig): boolean {
  return (
    COLOR_KEYS.some((key) => theme[key] !== undefined) ||
    DARK_COLOR_KEYS.some((key) => theme.dark?.[key] !== undefined)
  );
}

export function getThemePresetId(theme: ThemeConfig): string | undefined {
  if (!hasCustomColors(theme)) return DEFAULT_THEME_PRESET.id;
  return THEME_PRESETS.find(
    (preset) =>
      COLOR_KEYS.every((key) => theme[key] === preset.theme[key]) &&
      DARK_COLOR_KEYS.every(
        (key) => theme.dark?.[key] === preset.theme.dark?.[key],
      ),
  )?.id;
}

export function applyThemePreset(
  theme: ThemeConfig,
  presetId: string,
): ThemeConfig {
  const preset = THEME_PRESETS.find((item) => item.id === presetId);
  if (!preset) return theme;
  return {
    ...theme,
    accent: preset.theme.accent,
    accent_hover: preset.theme.accent_hover,
    accent_bg: preset.theme.accent_bg,
    dark: {
      ...theme.dark,
      ...preset.theme.dark,
    },
  };
}
