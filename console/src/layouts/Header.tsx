import { Layout, Space, Tooltip, Dropdown } from "antd";
import type { MenuProps } from "antd";
import { Button } from "@agentscope-ai/design";
import {
  DownOutlined,
  FileTextOutlined,
  GithubOutlined,
  InfoCircleOutlined,
  PlayCircleOutlined,
  ReadOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import LanguageSwitcher, {
  LANGUAGE_LIST,
} from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import { openExternalLink } from "../utils/openExternalLink";
import AppBrand from "./AppBrand";
import {
  GITHUB_URL,
  getDocsUrl,
  getFaqUrl,
  getFeatureDemosUrl,
  getReleaseNotesUrl,
} from "./constants";
import styles from "./index.module.less";

const { Header: AntHeader } = Layout;

export default function Header({ showBrand = false }: { showBrand?: boolean }) {
  const { t, i18n } = useTranslation();
  const { setThemeMode } = useTheme();

  const handleNavClick = (url: string) => {
    openExternalLink(url);
  };

  const resourcesMenuItems: MenuProps["items"] = [
    {
      key: "tutorial",
      icon: <ReadOutlined />,
      label: t("header.tutorial"),
      onClick: () => handleNavClick(getDocsUrl(i18n.language)),
    },
    {
      key: "featureDemos",
      icon: <PlayCircleOutlined />,
      label: t("header.featureDemos"),
      onClick: () => handleNavClick(getFeatureDemosUrl(i18n.language)),
    },
    {
      key: "changelog",
      icon: <FileTextOutlined />,
      label: t("header.changelog"),
      onClick: () => handleNavClick(getReleaseNotesUrl(i18n.language)),
    },
    {
      key: "faq",
      icon: <InfoCircleOutlined />,
      label: t("header.faq"),
      onClick: () => handleNavClick(getFaqUrl(i18n.language)),
    },
  ];

  const githubMenuItem: MenuProps["items"] = [
    {
      key: "github",
      icon: <GithubOutlined />,
      label: t("header.github"),
      onClick: () => handleNavClick(GITHUB_URL),
    },
  ];

  const mobileMenuItems: MenuProps["items"] = [
    {
      key: "language",
      label: t("sidebar.settings.language"),
      children: LANGUAGE_LIST.map(({ key, label }) => ({
        key,
        label,
        onClick: () => {
          i18n.changeLanguage(key);
          localStorage.setItem("language", key);
        },
      })),
    },
    {
      key: "theme",
      label: t("sidebar.settings.theme"),
      children: [
        {
          key: "light",
          label: t("theme.light"),
          onClick: () => setThemeMode("light"),
        },
        {
          key: "dark",
          label: t("theme.dark"),
          onClick: () => setThemeMode("dark"),
        },
        {
          key: "system",
          label: t("theme.system"),
          onClick: () => setThemeMode("system"),
        },
      ],
    },
    { type: "divider" },
    ...resourcesMenuItems,
    ...githubMenuItem,
  ];

  return (
    <AntHeader className={styles.header}>
      <div className={styles.headerPluginLeft}>
        {showBrand && <AppBrand />}
        <Slot name="header.left" kind="fill" />
      </div>
      <Space size="middle">
        <Slot name="header.right" kind="fill" />
        {resourcesMenuItems.length > 0 && (
          <Dropdown menu={{ items: resourcesMenuItems }}>
            <Button type="text" className={styles.hideOnMobile}>
              {t("header.resources")} <DownOutlined />
            </Button>
          </Dropdown>
        )}
        <Tooltip title={t("header.github")}>
          <Button
            type="text"
            icon={<GithubOutlined />}
            onClick={() => handleNavClick(GITHUB_URL)}
            className={styles.hideOnMobile}
          >
            {t("header.github")}
          </Button>
        </Tooltip>
        <div className={styles.headerDivider} />
        <span className={styles.hideOnMobile}>
          <LanguageSwitcher />
        </span>
        <span className={styles.hideOnMobile}>
          <ThemeToggleButton />
        </span>
        <Dropdown menu={{ items: mobileMenuItems }} placement="bottomRight">
          <Button
            type="text"
            icon={<InfoCircleOutlined />}
            className={styles.showOnMobile}
            title={t("header.resources")}
          />
        </Dropdown>
      </Space>
    </AntHeader>
  );
}
