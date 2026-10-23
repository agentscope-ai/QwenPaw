import { Layout, message, Tooltip, Dropdown } from "antd";
import type { MenuProps } from "antd";
import { Button } from "@agentscope-ai/design";
import {
  FileText as FileTextOutlined,
  Github as GithubOutlined,
  Info as InfoCircleOutlined,
  CirclePlay as PlayCircleOutlined,
  BookOpen as ReadOutlined,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import LanguageSwitcher, {
  LANGUAGE_LIST,
} from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import { applyLanguagePreference } from "../utils/languagePreference";
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
      icon: <ReadOutlined size="1em" />,
      label: t("header.tutorial"),
      onClick: () => handleNavClick(getDocsUrl(i18n.language)),
    },
    {
      key: "featureDemos",
      icon: <PlayCircleOutlined size="1em" />,
      label: t("header.featureDemos"),
      onClick: () => handleNavClick(getFeatureDemosUrl(i18n.language)),
    },
    {
      key: "changelog",
      icon: <FileTextOutlined size="1em" />,
      label: t("header.changelog"),
      onClick: () => handleNavClick(getReleaseNotesUrl(i18n.language)),
    },
    {
      key: "faq",
      icon: <InfoCircleOutlined size="1em" />,
      label: t("header.faq"),
      onClick: () => handleNavClick(getFaqUrl(i18n.language)),
    },
  ];

  const githubMenuItem: MenuProps["items"] = [
    {
      key: "github",
      icon: <GithubOutlined size="1em" />,
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
          applyLanguagePreference(i18n, key, {
            onPersistError: () =>
              message.error(t("agentConfig.languageSaveFailed")),
          });
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
    <AntHeader
      className={`${styles.header} ${
        showBrand ? styles.headerWithBrand : styles.headerPluginOnly
      }`}
    >
      <div className={styles.headerPluginLeft}>
        {showBrand && <AppBrand />}
        <Slot name="header.left" kind="fill" />
      </div>
      <div className={styles.headerActions}>
        <Slot name="header.right" kind="fill" />
        {showBrand && (
          <>
            <div className={styles.utilityGroup}>
              {resourcesMenuItems.length > 0 && (
                <Dropdown menu={{ items: resourcesMenuItems }}>
                  <Button
                    type="text"
                    className={styles.hideOnMobile}
                    aria-label={t("header.resources")}
                    icon={<ReadOutlined size={17} />}
                  />
                </Dropdown>
              )}
              <Tooltip title={t("header.github")}>
                <Button
                  type="text"
                  icon={<GithubOutlined size="1em" />}
                  onClick={() => handleNavClick(GITHUB_URL)}
                  className={styles.hideOnMobile}
                  aria-label={t("header.github")}
                />
              </Tooltip>
              <div className={styles.headerDivider} />
              <span className={styles.hideOnMobile}>
                <LanguageSwitcher />
              </span>
              <span className={styles.hideOnMobile}>
                <ThemeToggleButton />
              </span>
            </div>
            <Dropdown menu={{ items: mobileMenuItems }} placement="bottomRight">
              <Button
                type="text"
                icon={<InfoCircleOutlined size="1em" />}
                className={styles.showOnMobile}
                title={t("header.resources")}
              />
            </Dropdown>
          </>
        )}
      </div>
    </AntHeader>
  );
}
