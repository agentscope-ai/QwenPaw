import { createContext, useContext } from "react";

import {
  translate,
  type Language,
  type StringKey,
  type StringParams,
} from "./strings";

/**
 * Shared language state for the shell.
 *
 * `localStorage["language"]` is the single source of truth: the embedded
 * Context console's i18next reads the same key at boot, so the topbar
 * toggle drives both surfaces. `resolveInitialLanguage` writes the
 * resolved default back so a cold start cannot leave the console's own
 * fallback disagreeing with the shell.
 */

export const CONSOLE_LANGUAGE_KEY = "language";

export function resolveInitialLanguage(): Language {
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(CONSOLE_LANGUAGE_KEY);
  } catch {
    /* storage unavailable */
  }
  if (stored === "zh" || stored === "en") return stored;
  const fallback: Language = navigator.language?.toLowerCase().startsWith("zh")
    ? "zh"
    : "en";
  try {
    window.localStorage.setItem(CONSOLE_LANGUAGE_KEY, fallback);
  } catch {
    /* storage unavailable */
  }
  return fallback;
}

export function persistLanguage(language: Language): void {
  try {
    window.localStorage.setItem(CONSOLE_LANGUAGE_KEY, language);
  } catch {
    /* storage unavailable */
  }
}

const LanguageContext = createContext<Language>("en");

export const LanguageProvider = LanguageContext.Provider;

export function useLanguage(): Language {
  return useContext(LanguageContext);
}

export type Translator = (key: StringKey, params?: StringParams) => string;

export function useT(): Translator {
  const language = useLanguage();
  return (key, params) => translate(language, key, params);
}
