export type MobileLanguage = "en" | "zh";

// The current catalog is Chinese-first. Keep one language across every screen
// until the remaining hard-coded copy has been moved into the catalog.
export const mobileLanguage: MobileLanguage = "zh";

export function mobileText(zh: string, en: string): string {
  return mobileLanguage === "zh" ? zh : en;
}
