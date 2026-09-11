import { Dropdown } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Button, type MenuProps } from "antd";
import { settingsApi } from "../../api/modules/language";
import { LANGUAGE_LIST } from "../../constants/languageList";
import styles from "./index.module.less";
export { LANGUAGE_LIST };

const KNOWN_LANG_KEYS = new Set(LANGUAGE_LIST.map((lang) => lang.key));

interface LanguageSwitcherProps {
  persistRemotely?: boolean;
}

export default function LanguageSwitcher({
  persistRemotely = true,
}: LanguageSwitcherProps) {
  const { i18n } = useTranslation();

  const currentLanguage = i18n.resolvedLanguage || i18n.language;
  const currentLangKey = KNOWN_LANG_KEYS.has(currentLanguage)
    ? currentLanguage
    : currentLanguage.split("-")[0];

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
    if (!persistRemotely) {
      return;
    }
    settingsApi
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
