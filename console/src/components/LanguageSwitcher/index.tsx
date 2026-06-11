import { useTranslation } from "react-i18next";
import { languageApi } from "../../api/modules/language";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Globe } from "lucide-react";

interface LanguageConfig {
  key: string;
  label: string;
  /** Two-letter ISO emoji flag or short text shown in the trigger button. */
  flag: string;
}

const LANGUAGE_LIST: LanguageConfig[] = [
  { key: "en", label: "English", flag: "🇬🇧" },
  { key: "zh", label: "简体中文", flag: "🇨🇳" },
  { key: "ja", label: "日本語", flag: "🇯🇵" },
  { key: "ru", label: "Русский", flag: "🇷🇺" },
  { key: "pt-BR", label: "Português (Brasil)", flag: "🇧🇷" },
  { key: "id", label: "Bahasa Indonesia", flag: "🇮🇩" },
];

const KNOWN_LANG_KEYS = new Set(LANGUAGE_LIST.map((lang) => lang.key));

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();

  const currentLanguage = i18n.resolvedLanguage || i18n.language;
  const currentLangKey = KNOWN_LANG_KEYS.has(currentLanguage)
    ? currentLanguage
    : currentLanguage.split("-")[0];

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
    languageApi
      .updateLanguage(lang)
      .catch((err) =>
        console.error("Failed to save language preference:", err),
      );
  };

  const flagMap: Record<string, string> = Object.fromEntries(
    LANGUAGE_LIST.map(({ key, flag }) => [key, flag]),
  );

  const currentFlag = flagMap[currentLangKey];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8">
          {currentFlag ? (
            <span className="text-base leading-none" aria-hidden="true">
              {currentFlag}
            </span>
          ) : (
            <Globe size={16} aria-hidden="true" />
          )}
          <span className="sr-only">Change language</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {LANGUAGE_LIST.map(({ key, label, flag }) => (
          <DropdownMenuItem
            key={key}
            onClick={() => changeLanguage(key)}
            className={cn(currentLangKey === key && "bg-accent")}
          >
            <span className="text-base leading-none mr-1" aria-hidden="true">
              {flag}
            </span>
            <span>{label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
