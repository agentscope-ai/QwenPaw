import type { ReactElement } from "react";
import {
  Languages as SparkChinese02Line,
  Languages as SparkEnglish02Line,
  Languages as SparkJapanLine,
  Languages as SparkRusLine,
  Languages as SparkPtLine,
} from "lucide-react";
import LanguageBadge from "../components/LanguageBadge";

export interface LanguageConfig {
  key: string;
  label: string;
  icon: ReactElement;
}

export const LANGUAGE_LIST: LanguageConfig[] = [
  { key: "en", label: "English", icon: <SparkEnglish02Line size="1em" /> },
  { key: "zh", label: "简体中文", icon: <SparkChinese02Line size="1em" /> },
  { key: "ja", label: "日本語", icon: <SparkJapanLine size="1em" /> },
  { key: "ru", label: "Русский", icon: <SparkRusLine size="1em" /> },
  {
    key: "pt-BR",
    label: "Português (Brasil)",
    icon: <SparkPtLine size="1em" />,
  },
  // The icon set has no Indonesian or Vietnamese letter badge. Reusing
  // the English one would advertise "en" next to a non-English label,
  // so these render the same badge style locally instead.
  { key: "id", label: "Bahasa Indonesia", icon: <LanguageBadge code="ID" /> },
  { key: "vi", label: "Tiếng Việt", icon: <LanguageBadge code="VI" /> },
];
