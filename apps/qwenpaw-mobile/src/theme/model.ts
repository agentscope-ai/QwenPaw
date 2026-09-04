export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export function normalizeThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

export function resolveTheme(
  preference: ThemePreference,
  systemTheme: ResolvedTheme | "unspecified" | null | undefined,
): ResolvedTheme {
  if (preference !== "system") return preference;
  return systemTheme === "dark" ? "dark" : "light";
}
