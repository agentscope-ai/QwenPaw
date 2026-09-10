import {
  DynamicColorIOS,
  Platform,
  PlatformColor,
  type ColorValue,
} from "react-native";

function semanticColor(
  light: string,
  dark: string,
  android?: string,
): ColorValue {
  if (Platform.OS === "ios") return DynamicColorIOS({ light, dark });
  if (Platform.OS === "android" && android) return PlatformColor(android);
  return light;
}

export const colors = {
  canvas: semanticColor(
    "#EBE7DF",
    "#0E0D0C",
    "@color/qwenpaw_canvas",
  ),
  groupedBackground: semanticColor(
    "#F6F3ED",
    "#151412",
    "@color/qwenpaw_grouped_background",
  ),
  surface: semanticColor(
    "#FFFDF9",
    "#211F1C",
    "@color/qwenpaw_surface",
  ),
  surfaceStrong: semanticColor(
    "#FFFFFF",
    "#2E2B27",
    "@color/qwenpaw_surface_strong",
  ),
  surfaceSoft: semanticColor(
    "#EEEAE2",
    "#2A2723",
    "@color/qwenpaw_surface_soft",
  ),
  tabBar: semanticColor(
    "#FFFDF9",
    "#211F1C",
    "@color/qwenpaw_tab_bar",
  ),
  searchBackground: semanticColor(
    "#EEEAE2",
    "#2A2723",
    "@color/qwenpaw_search_background",
  ),
  pressed: semanticColor("#E7E1D8", "#35312C", "@color/qwenpaw_pressed"),
  ink: semanticColor(
    "#1D1B18",
    "#F6F1E9",
    "@color/qwenpaw_ink",
  ),
  muted: semanticColor(
    "#66615B",
    "#AAA39A",
    "@color/qwenpaw_muted",
  ),
  faint: semanticColor(
    "#6D6760",
    "#8E877F",
    "@color/qwenpaw_faint",
  ),
  line: semanticColor("#E4DDD4", "#37332E", "@color/qwenpaw_line"),
  hairline: semanticColor(
    "#DED6CC",
    "#3D3933",
    "@color/qwenpaw_hairline",
  ),
  accent: "#C84D08",
  accentDark: semanticColor(
    "#A94008",
    "#FFA06B",
    "@color/qwenpaw_accent_dark",
  ),
  accentSoft: semanticColor(
    "#FFF0E5",
    "#3B261B",
    "@color/qwenpaw_accent_soft",
  ),
  positive: semanticColor(
    "#2F7B56",
    "#70C496",
    "@color/qwenpaw_positive",
  ),
  danger: semanticColor(
    "#A63F39",
    "#FF8B83",
    "@color/qwenpaw_danger",
  ),
  scrim: semanticColor(
    "rgba(20, 15, 12, 0.30)",
    "rgba(0, 0, 0, 0.62)",
    "@color/qwenpaw_scrim",
  ),
  black: "#1C1917",
  white: "#FFFFFF",
} as const;

export const spacing = {
  xs: 6,
  sm: 10,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 12,
  md: 18,
  lg: 24,
  pill: 999,
} as const;
