import type { ReactElement } from "react";
import {
  SparkChinese02Line,
  SparkEnglish02Line,
  SparkJapanLine,
  SparkRusLine,
  SparkPtLine,
} from "@agentscope-ai/icons";

export interface LanguageConfig {
  key: string;
  label: string;
  icon: ReactElement;
}

/**
 * Single source of truth for the selectable UI languages, shared by every
 * language selector (top-right dropdown, header language menu, and the
 * sidebar settings gear).
 *
 * Kept in a side-effect-free module — it imports only icons, never a
 * component or CSS module — so consumers can read the list without pulling
 * in UI dependencies or coupling to a specific component implementation.
 */
export const LANGUAGE_LIST: LanguageConfig[] = [
  { key: "en", label: "English", icon: <SparkEnglish02Line /> },
  { key: "zh", label: "简体中文", icon: <SparkChinese02Line /> },
  { key: "ja", label: "日本語", icon: <SparkJapanLine /> },
  { key: "ru", label: "Русский", icon: <SparkRusLine /> },
  { key: "pt-BR", label: "Português (Brasil)", icon: <SparkPtLine /> },
  { key: "id", label: "Bahasa Indonesia", icon: <SparkEnglish02Line /> },
  { key: "vi", label: "Tiếng Việt", icon: <SparkEnglish02Line /> },
];
