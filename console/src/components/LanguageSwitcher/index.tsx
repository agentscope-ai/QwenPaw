import { Dropdown } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Button, type MenuProps } from "antd";
import { languageApi } from "../../api/modules/language";
import styles from "./index.module.less";
import {
  SparkChinese02Line,
  SparkEnglish02Line,
  SparkJapanLine,
  SparkRusLine,
  SparkPtLine,
} from "@agentscope-ai/icons";

interface LanguageConfig {
  key: string;
  label: string;
  icon: React.ReactElement;
}

const LANGUAGE_LIST: LanguageConfig[] = [
  { key: "en", label: "English", icon: <SparkEnglish02Line /> },
  { key: "zh", label: "简体中文", icon: <SparkChinese02Line /> },
  { key: "ja", label: "日本語", icon: <SparkJapanLine /> },
  { key: "ru", label: "Русский", icon: <SparkRusLine /> },
  { key: "pt-BR", label: "Português (Brasil)", icon: <SparkPtLine /> },
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

  const items: MenuProps["items"] = LANGUAGE_LIST.map(({ key, label }) => ({
    key,
    label,
    onClick: () => changeLanguage(key),
  }));

  const iconMap: Record<string, React.ReactElement> = Object.fromEntries(
    LANGUAGE_LIST.map(({ key, icon }) => [key, icon]),
  );

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLangKey] }}
      placement="bottomRight"
      overlayClassName={styles.languageDropdown}
    >
      <Button icon={iconMap[currentLangKey]} type="text" />
    </Dropdown>
  );
}
