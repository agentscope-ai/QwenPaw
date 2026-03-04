import { Dropdown, Button } from "@agentscope-ai/design";
import { GlobalOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { MenuProps } from "antd";

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();

  const currentLanguage = i18n.language;

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
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
      key: "fr",
      label: "Français",
      onClick: () => changeLanguage("fr"),
    },
  ];

  const languageLabels: Record<string, string> = {
    en: "English",
    zh: "简体中文",
    fr: "Français",
  };
  const currentLabel = languageLabels[currentLanguage] ?? "English";

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLanguage] }}
      placement="bottomRight"
    >
      <Button icon={<GlobalOutlined />} type="text">
        {currentLabel}
      </Button>
    </Dropdown>
  );
}
