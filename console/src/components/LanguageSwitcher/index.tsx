import { Dropdown } from "@agentscope-ai/design";
import { GlobalOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Button, type MenuProps } from "antd";
import { languageApi } from "../../api/modules/language";
import styles from "./index.module.less";

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

  // const languageIcons: Record<string, string> = {
  //   en: "https://gw.alicdn.com/imgextra/i1/O1CN015nxrjZ1JkjjTH3DLE_!!6000000001067-2-tps-80-80.png",
  //   ru: "https://gw.alicdn.com/imgextra/i4/O1CN01QjtbJU1HWQ7WlCXce_!!6000000000765-2-tps-80-80.png",
  //   zh: "https://gw.alicdn.com/imgextra/i3/O1CN01L3Tjzd22UqhdBWnXO_!!6000000007124-2-tps-80-80.png",
  //   ja: "https://gw.alicdn.com/imgextra/i3/O1CN019bbf8m1y6L2lor0bZ_!!6000000006529-2-tps-80-80.png",
  // };

  // const currentLabel = languageIcons[currentLanguage] ?? <GlobalOutlined />;

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLangKey] }}
      placement="bottomRight"
      overlayClassName={styles.languageDropdown}
    >
      {/* <img
        className={styles.languageIcon}
        src={currentLabel as string}
        alt="Language"
      /> */}
      <Button icon={<GlobalOutlined />} type="text" />
    </Dropdown>
  );
}
