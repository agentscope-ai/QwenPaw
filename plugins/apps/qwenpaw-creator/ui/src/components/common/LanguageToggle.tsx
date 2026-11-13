import { useState } from "react";
import { Dropdown, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { useLocaleStore } from "@/store/localeStore";

interface LanguageToggleProps {
  className?: string;
}

const LANGUAGE_OPTIONS = [
  { key: "en", label: "English" },
  { key: "zh", label: "简体中文" },
];

export default function LanguageToggle({ className }: LanguageToggleProps) {
  const { t } = useTranslation();
  const language = useLocaleStore((state) => state.language);
  const setLanguage = useLocaleStore((state) => state.setLanguage);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const menuItems = LANGUAGE_OPTIONS.map((option) => ({
    key: option.key,
    label: option.label,
    onClick: () => setLanguage(option.key),
  }));

  const button = (
    <button
      type="button"
      className={className}
      aria-label={t("common.language")}
    >
      {language === "zh" ? "中" : "EN"}
    </button>
  );

  return (
    <Dropdown
      trigger={["click"]}
      menu={{ items: menuItems }}
      open={dropdownOpen}
      onOpenChange={setDropdownOpen}
    >
      {dropdownOpen ? (
        button
      ) : (
        <Tooltip title={t("common.language")}>{button}</Tooltip>
      )}
    </Dropdown>
  );
}
