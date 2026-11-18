import { useMemo, useSyncExternalStore } from "react";
import {
  defaultDarkTheme,
  defaultLightTheme,
  type Theme,
  type TypographyTheme,
} from "@openuidev/react-ui";

// Keep OpenUI's layout and chart palettes; map its semantic roles to the host.
// CSS variables also reach portals through OpenUI's ThemeProvider.
const hostTokens = {
  background: "bg",
  foreground: "surface",
  popoverBackground: "surface-raised",
  sunkLight: "fill-faint",
  sunk: "surface-sunken",
  sunkDeep: "fill",
  elevatedLight: "fill-subtle",
  elevated: "fill",
  elevatedStrong: "fill-strong",
  highlightSubtle: "fill-faint",
  highlight: "fill-subtle",
  highlightStrong: "fill",
  highlightIntense: "fill-strong",
  textNeutralPrimary: "text",
  textNeutralSecondary: "text-secondary",
  textNeutralTertiary: "text-tertiary",
  textNeutralLink: "accent-text",
  textBrand: "accent-text",
  textAccentPrimary: "text-inverse",
  interactiveAccentDefault: "accent",
  interactiveAccentHover: "accent-hover",
  interactiveAccentPressed: "accent-active",
  interactiveAccentDisabled: "accent-soft",
  borderDefault: "border-subtle",
  borderInteractive: "border",
  borderInteractiveEmphasis: "border-hover",
  borderInteractiveSelected: "focus-ring",
  borderAccent: "accent-border",
  borderAccentEmphasis: "focus-ring",
  infoBackground: "info-bg",
  textInfoPrimary: "info-text",
  borderInfo: "info-border",
  borderInfoEmphasis: "info-text",
  successBackground: "success-bg",
  textSuccessPrimary: "success-text",
  borderSuccess: "success-border",
  borderSuccessEmphasis: "success",
  alertBackground: "warning-bg",
  textAlertPrimary: "warning-text",
  borderAlert: "warning-border",
  borderAlertEmphasis: "warning",
  dangerBackground: "error-bg",
  textDangerPrimary: "error-text",
  textDangerSecondary: "error-text",
  textDangerTertiary: "error",
  borderDanger: "error-border",
  borderDangerEmphasis: "error",
  interactiveDestructiveDefault: "error-faint",
  interactiveDestructiveHover: "error-bg",
  interactiveDestructivePressed: "error-bg",
  interactiveDestructiveDisabled: "error-faint",
  interactiveDestructiveAccentDefault: "error",
  interactiveDestructiveAccentHover: "error-text",
  interactiveDestructiveAccentPressed: "error-text",
  interactiveDestructiveAccentDisabled: "error-border",
  radiusM: "radius",
  radiusL: "radius",
  radiusXl: "radius-card",
  radius2xl: "radius-card",
  radius3xl: "radius-card",
  radius5xl: "radius-panel",
  shadowS: "shadow-sm",
  shadowM: "shadow-md",
  shadowL: "shadow-panel",
  shadowXl: "shadow-panel",
} satisfies Partial<Record<keyof Theme, string>>;

const fontFamily =
  'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const codeFamily = '"SFMono-Regular", Consolas, "Liberation Mono", monospace';

function typography(scale: number): TypographyTheme {
  const px = (size: number) => `${Math.round(size * scale * 1000) / 1000}px`;
  const font = (size: number, weight = 400, lineHeight = 1.5, code = false) =>
    `${weight} ${px(size)}/${lineHeight} ${code ? codeFamily : fontFamily}`;
  const theme: TypographyTheme = {
    fontBody: fontFamily,
    fontHeading: fontFamily,
    fontLabel: fontFamily,
    fontNumbers: fontFamily,
    fontCode: codeFamily,
    fontWeightRegular: "400",
    fontWeightMedium: "500",
    textCodeSm: font(12, 400, 1.5, true),
    textCodeSmHeavy: font(12, 700, 1.5, true),
    textCodeDefault: font(13, 400, 1.5, true),
    textCodeDefaultHeavy: font(13, 700, 1.5, true),
  };
  for (const [size, value] of Object.entries({
    "2xs": 10,
    Xs: 12,
    Sm: 13,
    Md: 14,
    Lg: 16,
    Xl: 20,
    "2xl": 24,
    "3xl": 28,
    "4xl": 32,
    "5xl": 36,
  }))
    theme[`fontSize${size}` as keyof TypographyTheme] = px(value);

  // Components use compound `font` tokens, not just fontBody/fontSizeMd.
  for (const role of ["Body", "Label", "Numbers"] as const) {
    for (const [size, value] of Object.entries({
      Xs: 12,
      Sm: 13,
      Default: 14,
      Lg: 16,
    })) {
      const lineHeight = role === "Label" ? 1.25 : 1.5;
      theme[`text${role}${size}` as keyof TypographyTheme] = font(
        value,
        400,
        lineHeight,
      );
      theme[`text${role}${size}Heavy` as keyof TypographyTheme] = font(
        value,
        500,
        lineHeight,
      );
    }
  }
  for (const [size, value] of Object.entries({
    Xs: 14,
    Sm: 16,
    Md: 20,
    Lg: 24,
    Xl: 28,
  })) {
    theme[`textHeading${size}` as keyof TypographyTheme] = font(
      value,
      600,
      1.25,
    );
    if (size !== "Xs")
      theme[`textNumbersHeading${size}` as keyof TypographyTheme] = font(
        value,
        600,
        1.25,
      );
  }
  return theme;
}

function createHostTheme(defaults: Theme, fonts: Theme): Theme {
  const theme: Theme = { ...fonts };
  for (const [key, token] of Object.entries(hostTokens)) {
    const name = key as keyof typeof hostTokens;
    const fallback = defaults[name];
    theme[name] = `var(--app-${token}${fallback ? `, ${fallback}` : ""})`;
  }
  return theme;
}

const listeners = new Set<() => void>();
let observer: MutationObserver | undefined;
let chartFontStyle: HTMLStyleElement | undefined;
let currentScale = 1;

function fontScale() {
  const scale = Number.parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue(
      "--app-font-scale",
    ),
  );
  return Number.isFinite(scale) && scale > 0 ? scale : 1;
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  if (!observer) {
    chartFontStyle = document.createElement("style");
    chartFontStyle.dataset.qwenpawOpenuiFont = "";
    document.head.appendChild(chartFontStyle);
    const update = () => {
      currentScale = fontScale();
      // OpenUI 0.18 measures canvas labels during render, before its provider
      // commits new CSS. Publish this one measurement token before notifying
      // React, so the cached widths and the displayed font stay in sync.
      chartFontStyle!.textContent = `:where(.qwenpaw-openui, [class*="openui-theme-portal-"]) {
        --openui-text-label-xs: ${
          typography(currentScale).textLabelXs
        } !important;
      }`;
      listeners.forEach((notify) => notify());
    };
    observer = new MutationObserver(update);
    update();
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["style", "class"],
    });
  }
  return () => {
    listeners.delete(onChange);
    if (!listeners.size) {
      observer?.disconnect();
      observer = undefined;
      chartFontStyle?.remove();
      chartFontStyle = undefined;
    }
  };
}

function getFontScale() {
  // A simultaneous host theme render must not see the new size until its
  // measurement CSS has been published by the observer.
  return observer ? currentScale : fontScale();
}

export function useOpenUITheme() {
  // Charts measure labels on canvas and cache by theme font string. Resolve
  // sizes here so changing the host preference remeasures without a remount.
  const scale = useSyncExternalStore(subscribe, getFontScale, () => 1);
  return useMemo(() => {
    const fonts = typography(scale);
    return {
      lightTheme: createHostTheme(defaultLightTheme, fonts),
      darkTheme: createHostTheme(defaultDarkTheme, fonts),
    };
  }, [scale]);
}
