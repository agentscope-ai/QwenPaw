import { Popover, Segmented, Select } from "antd";
import {
  ChevronRight,
  CircleDot,
  GitBranch,
  Github,
  Info,
  Monitor,
  Moon,
  Palette,
  Settings,
  Sun,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { languageApi } from "../api/modules/language";
import { useTheme, type ThemeMode } from "../contexts/ThemeContext";
import { openExternalLink } from "../utils/openExternalLink";
import { GITHUB_URL } from "./constants";
import styles from "./sidebarSettingsPanel.module.less";

const GITHUB_ISSUES_URL = `${GITHUB_URL}/issues`;
const GITHUB_RELEASES_URL = `${GITHUB_URL}/releases`;

const LANGUAGES = [
  { value: "zh", label: "简体中文" },
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
  { value: "ru", label: "Русский" },
  { value: "id", label: "Bahasa Indonesia" },
  { value: "vi", label: "Tiếng Việt" },
  { value: "pt-BR", label: "Português" },
];

interface SidebarSettingsPanelProps {
  version?: string;
  onClose?: () => void;
  onOpenSettings: () => void;
  onOpenAbout: () => void;
}

export default function SidebarSettingsPanel({
  version,
  onClose,
  onOpenSettings,
  onOpenAbout,
}: SidebarSettingsPanelProps) {
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
  const rawLanguage = i18n.resolvedLanguage || i18n.language || "en";
  const currentLanguage = LANGUAGES.some(
    (language) => language.value === rawLanguage,
  )
    ? rawLanguage
    : rawLanguage.split("-")[0];

  const changeLanguage = (language: string) => {
    void i18n.changeLanguage(language);
    localStorage.setItem("language", language);
    void languageApi.updateLanguage(language).catch(() => {});
  };

  const openLink = (url: string) => {
    onClose?.();
    openExternalLink(url);
  };

  const appearanceContent = (
    <div className={styles.subPanel}>
      <label className={styles.field}>
        <span>{t("sidebar.settings.language", "Language")}</span>
        <Select
          value={currentLanguage}
          options={LANGUAGES}
          onChange={changeLanguage}
        />
      </label>
      <div className={styles.field}>
        <span>{t("sidebar.settings.theme", "Theme")}</span>
        <Segmented<ThemeMode>
          value={themeMode}
          options={[
            {
              value: "light",
              label: <Sun size={15} aria-label={t("theme.light")} />,
            },
            {
              value: "dark",
              label: <Moon size={15} aria-label={t("theme.dark")} />,
            },
            {
              value: "system",
              label: <Monitor size={15} aria-label={t("theme.system")} />,
            },
          ]}
          onChange={setThemeMode}
        />
      </div>
    </div>
  );

  const githubContent = (
    <div className={styles.linkPanel}>
      <button type="button" onClick={() => openLink(GITHUB_URL)}>
        <Github size={16} />
        {t("sidebar.quickMenu.repository", "Repository")}
      </button>
      <button type="button" onClick={() => openLink(GITHUB_ISSUES_URL)}>
        <CircleDot size={16} />
        {t("sidebar.quickMenu.issues", "Issues")}
      </button>
      <button type="button" onClick={() => openLink(GITHUB_RELEASES_URL)}>
        <GitBranch size={16} />
        {t("sidebar.quickMenu.releases", "Releases")}
      </button>
    </div>
  );

  return (
    <div className={styles.panel}>
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => {
          onClose?.();
          onOpenSettings();
        }}
      >
        <Settings size={17} />
        <span>{t("sidebar.quickMenu.settings", "Settings")}</span>
      </button>

      <Popover
        placement="rightTop"
        trigger="click"
        content={appearanceContent}
        overlayClassName={styles.nestedPopover}
      >
        <button type="button" className={styles.menuItem}>
          <Palette size={17} />
          <span>{t("sidebar.quickMenu.appearance", "Appearance")}</span>
          <ChevronRight className={styles.chevron} size={16} />
        </button>
      </Popover>

      <div className={styles.divider} />

      <button
        type="button"
        className={styles.menuItem}
        onClick={() => {
          onClose?.();
          onOpenAbout();
        }}
      >
        <Info size={17} />
        <span>{t("sidebar.quickMenu.about", "About QwenPaw")}</span>
      </button>

      <Popover
        placement="rightBottom"
        trigger="click"
        content={githubContent}
        overlayClassName={styles.nestedPopover}
      >
        <button type="button" className={styles.menuItem}>
          <Github size={17} />
          <span>{t("sidebar.quickMenu.github", "GitHub")}</span>
          <ChevronRight className={styles.chevron} size={16} />
        </button>
      </Popover>

      <div className={styles.version}>
        QwenPaw {version ? `v${version}` : ""}
      </div>
    </div>
  );
}
