export type MobileLanguage = "en" | "zh";

function resolveLanguage(): MobileLanguage {
  try {
    const locale = Intl.DateTimeFormat().resolvedOptions().locale;
    return locale.toLowerCase().startsWith("zh") ? "zh" : "en";
  } catch {
    return "en";
  }
}

export const mobileLanguage = resolveLanguage();

export function mobileText(zh: string, en: string): string {
  return mobileLanguage === "zh" ? zh : en;
}
