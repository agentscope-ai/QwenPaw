import { Dropdown, Button } from "@agentscope-ai/design";
import { GlobalOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { MenuProps } from "antd";

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();

  const currentLanguage = i18n.resolvedLanguage || i18n.language;

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
      key: "ru",
      label: "Русский",
      onClick: () => changeLanguage("ru"),
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
  ];

  const languageLabels: Record<string, string> = {
    en: "English",
    ru: "Русский",
    zh: "简体中文",
    ja: "日本語",
  };

  const currentLabel = languageLabels[currentLanguage] ?? "English";

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLanguage.split("-")[0]] }}
      placement="bottomRight"
    >
      <Button icon={<GlobalOutlined />} type="text">
        {currentLabel}
      </Button>
    </Dropdown>
  );
}
