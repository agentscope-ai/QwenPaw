import type { i18n as I18nInstance } from "i18next";

import { settingsApi } from "@/api/modules/language";

interface ApplyLanguagePreferenceOptions {
  /**
   * Skip the remote write. Used by selectors that intentionally keep
   * the choice local only.
   */
  persistRemotely?: boolean;
  /**
   * Called when the remote write is rejected, so every selector can
   * tell the user instead of silently losing the preference.
   */
  onPersistError?: (error: unknown) => void;
}

/**
 * Single implementation of the language preference contract shared by
 * every language selector (header dropdown, mobile header menu,
 * sidebar settings panel and General Settings).
 *
 * Switching i18next and remembering the choice locally always succeed,
 * which is why a rejected remote write used to go unnoticed: the UI
 * showed the new language while the server kept the old one. Routing
 * all four entry points through here keeps them from drifting apart
 * again and makes the rejection observable.
 */
export function applyLanguagePreference(
  i18n: I18nInstance,
  language: string,
  {
    persistRemotely = true,
    onPersistError,
  }: ApplyLanguagePreferenceOptions = {},
): void {
  void i18n.changeLanguage(language);
  localStorage.setItem("language", language);
  if (!persistRemotely) {
    return;
  }
  void settingsApi.updateLanguage(language).catch((error: unknown) => {
    console.error("Failed to save language preference:", error);
    onPersistError?.(error);
  });
}
