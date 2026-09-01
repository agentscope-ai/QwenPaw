import { Popover } from "antd";
import {
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  Github,
  Info,
  Languages,
  Monitor,
  Moon,
  Palette,
  PlayCircle,
  Settings,
  Sun,
  UnfoldHorizontal,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { languageApi } from "../api/modules/language";
import { useTheme, type ThemeMode } from "../contexts/ThemeContext";
import {
  getChatWideModePreference,
  setChatWideModePreference,
} from "../utils/chatLayoutPreference";
import { openExternalLink } from "../utils/openExternalLink";
import {
  GITHUB_URL,
  getDocsUrl,
  getFaqUrl,
  getFeatureDemosUrl,
  getReleaseNotesUrl,
} from "./constants";
import styles from "./sidebarSettingsPanel.module.less";

type ContentWidth = "standard" | "wide";

const QWENPAW_WEBSITE_URL = "https://qwenpaw.agentscope.io/";

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
  onOpenDesktopMode: () => void;
  onOpenSettings: () => void;
}

interface FlyoutItemProps {
  icon: ReactNode;
  label: ReactNode;
  content: ReactNode;
}

function FlyoutItem({ icon, label, content }: FlyoutItemProps) {
  return (
    <Popover
      placement="rightTop"
      trigger={["hover", "click"]}
      content={content}
      overlayClassName={styles.nestedPopover}
      destroyOnHidden
      mouseEnterDelay={0.08}
      mouseLeaveDelay={0.12}
    >
      <button type="button" className={styles.menuItem}>
        {icon}
        <span>{label}</span>
        <ChevronRight className={styles.chevron} size={15} />
      </button>
    </Popover>
  );
}

interface Choice<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
}

function ChoicePanel<T extends string>({
  choices,
  value,
  onChange,
}: {
  choices: Choice<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className={styles.choicePanel}>
      {choices.map((choice) => {
        const selected = choice.value === value;
        return (
          <button
            type="button"
            key={choice.value}
            className={`${styles.choiceItem} ${
              selected ? styles.choiceItemSelected : ""
            }`}
            aria-current={selected ? "true" : undefined}
            onClick={() => onChange(choice.value)}
          >
            {choice.icon}
            <span>{choice.label}</span>
            {selected && <Check className={styles.check} size={16} />}
          </button>
        );
      })}
    </div>
  );
}

export default function SidebarSettingsPanel({
  version,
  onClose,
  onOpenDesktopMode,
  onOpenSettings,
}: SidebarSettingsPanelProps) {
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
  const [wideMode, setWideMode] = useState(getChatWideModePreference);
  const rawLanguage = i18n.resolvedLanguage || i18n.language || "en";
  const currentLanguage = LANGUAGES.some(
    (language) => language.value === rawLanguage,
  )
    ? rawLanguage
    : rawLanguage.split("-")[0];

  const finishAction = (action: () => void) => {
    action();
    onClose?.();
  };

  const changeLanguage = (language: string) => {
    finishAction(() => {
      void i18n.changeLanguage(language);
      localStorage.setItem("language", language);
      void languageApi.updateLanguage(language).catch(() => {});
    });
  };

  const changeTheme = (theme: ThemeMode) => {
    finishAction(() => setThemeMode(theme));
  };

  const changeContentWidth = (width: ContentWidth) => {
    const enabled = width === "wide";
    finishAction(() => {
      setChatWideModePreference(enabled);
      setWideMode(enabled);
    });
  };

  const openLink = (url: string) => {
    finishAction(() => openExternalLink(url));
  };

  const languageChoices = (
    <ChoicePanel
      choices={LANGUAGES}
      value={currentLanguage}
      onChange={changeLanguage}
    />
  );

  const themeChoices = (
    <ChoicePanel<ThemeMode>
      choices={[
        {
          value: "light",
          label: t("theme.light", "Light"),
          icon: <Sun size={15} />,
        },
        {
          value: "dark",
          label: t("theme.dark", "Dark"),
          icon: <Moon size={15} />,
        },
        {
          value: "system",
          label: t("theme.system", "System"),
          icon: <Monitor size={15} />,
        },
      ]}
      value={themeMode}
      onChange={changeTheme}
    />
  );

  const widthChoices = (
    <ChoicePanel<ContentWidth>
      choices={[
        {
          value: "standard",
          label: t("settingsCenter.contentWidthStandard", "Standard"),
        },
        {
          value: "wide",
          label: t("settingsCenter.contentWidthWide", "Wide"),
        },
      ]}
      value={wideMode ? "wide" : "standard"}
      onChange={changeContentWidth}
    />
  );

  const preferencesContent = (
    <div className={styles.flyoutPanel}>
      <FlyoutItem
        icon={<Languages size={16} />}
        label={t("sidebar.settings.language", "Language")}
        content={languageChoices}
      />
      <FlyoutItem
        icon={<Palette size={16} />}
        label={t("sidebar.settings.theme", "Theme")}
        content={themeChoices}
      />
      <FlyoutItem
        icon={<UnfoldHorizontal size={16} />}
        label={t("settingsCenter.contentWidth", "Content width")}
        content={widthChoices}
      />
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => finishAction(onOpenDesktopMode)}
      >
        <Monitor size={16} />
        <span>{t("sidebar.settings.desktopMode", "Desktop mode")}</span>
      </button>
    </div>
  );

  return (
    <div className={styles.panel}>
      <FlyoutItem
        icon={<Palette size={16} />}
        label={t("sidebar.quickMenu.preferences", "Preferences")}
        content={preferencesContent}
      />
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => finishAction(onOpenSettings)}
      >
        <Settings size={16} />
        <span>{t("sidebar.quickMenu.settings", "Settings")}</span>
      </button>

      <div className={styles.divider} />

      <button
        type="button"
        className={styles.menuItem}
        onClick={() => openLink(getDocsUrl(i18n.language))}
      >
        <BookOpen size={16} />
        <span>{t("header.tutorial", "Tutorial")}</span>
      </button>
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => openLink(getFeatureDemosUrl(i18n.language))}
      >
        <PlayCircle size={16} />
        <span>{t("header.featureDemos", "Feature demos")}</span>
      </button>
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => openLink(getReleaseNotesUrl(i18n.language))}
      >
        <FileText size={16} />
        <span>{t("header.changelog", "Changelog")}</span>
      </button>
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => openLink(getFaqUrl(i18n.language))}
      >
        <CircleHelp size={16} />
        <span>{t("header.faq", "FAQ")}</span>
      </button>
      <button
        type="button"
        className={styles.menuItem}
        onClick={() => openLink(GITHUB_URL)}
      >
        <Github size={16} />
        <span>{t("sidebar.quickMenu.github", "GitHub")}</span>
      </button>

      <div className={styles.divider} />

      <button
        type="button"
        className={styles.menuItem}
        onClick={() => openLink(QWENPAW_WEBSITE_URL)}
      >
        <Info size={16} />
        <span>{t("sidebar.quickMenu.about", "About QwenPaw")}</span>
        {version && <span className={styles.menuMeta}>v{version}</span>}
      </button>
    </div>
  );
}
