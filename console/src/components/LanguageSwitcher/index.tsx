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
} from "@agentscope-ai/icons";

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();

  const currentLanguage = i18n.resolvedLanguage || i18n.language;
  const currentLangKey = currentLanguage.split("-")[0];

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
    languageApi
      .updateLanguage(lang)
      .catch((err) =>
        console.error("Failed to save language preference:", err),
      );
  };

  const items: MenuProps["items"] = [
    {
      key: "en",
      label: "English",
      onClick: () => changeLanguage("en"),
    },
    {
      key: "zh",
      label: "简体中文",
      onClick: () => changeLanguage("zh"),
    },
    {
      key: "ja",
      label: "日本語",
      onClick: () => changeLanguage("ja"),
    },
    {
      key: "ru",
      label: "Русский",
      onClick: () => changeLanguage("ru"),
    },
  ];

  const LIGHT_ICON: Record<string, React.ReactElement> = {
    en: <SparkEnglish02Line />,
    zh: <SparkChinese02Line />,
    ja: <SparkJapanLine />,
    ru: <SparkRusLine />,
  };

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLangKey] }}
      placement="bottomRight"
      overlayClassName={styles.languageDropdown}
    >
      <Button icon={LIGHT_ICON[currentLangKey]} type="text" />
    </Dropdown>
  );
}
