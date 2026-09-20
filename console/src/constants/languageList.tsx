import type { ReactElement } from "react";
import {
  SparkChinese02Line,
  SparkEnglish02Line,
  SparkJapanLine,
  SparkRusLine,
  SparkPtLine,
} from "@agentscope-ai/icons";
import LanguageBadge from "../components/LanguageBadge";

export interface LanguageConfig {
  key: string;
  label: string;
  icon: ReactElement;
}

export const LANGUAGE_LIST: LanguageConfig[] = [
  { key: "en", label: "English", icon: <SparkEnglish02Line /> },
  { key: "zh", label: "简体中文", icon: <SparkChinese02Line /> },
  { key: "ja", label: "日本語", icon: <SparkJapanLine /> },
  { key: "ru", label: "Русский", icon: <SparkRusLine /> },
  { key: "pt-BR", label: "Português (Brasil)", icon: <SparkPtLine /> },
  // The icon set has no Indonesian or Vietnamese letter badge. Reusing
  // the English one would advertise "en" next to a non-English label,
  // so these render the same badge style locally instead.
  { key: "id", label: "Bahasa Indonesia", icon: <LanguageBadge code="ID" /> },
  { key: "vi", label: "Tiếng Việt", icon: <LanguageBadge code="VI" /> },
];
