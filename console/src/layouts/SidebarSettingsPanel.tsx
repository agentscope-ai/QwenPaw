import { Popover } from "antd";
import {
  BookOpen,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  Info,
  Languages,
  ListCollapse,
  LogOut,
  MessageSquareText,
  Monitor,
  Moon,
  Palette,
  Settings,
  Sun,
  UnfoldHorizontal,
  UserRound,
  Wrench,
} from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { languageApi } from "../api/modules/language";
import { useTheme, type ThemeMode } from "../contexts/ThemeContext";
import {
  getChatWideModePreference,
  setChatWideModePreference,
} from "../utils/chatLayoutPreference";
import {
  getAssistantMessageDisplayPreference,
  getShowThinkingPreference,
  getToolDisplayPreference,
  setAssistantMessageDisplayPreference,
  setShowThinkingPreference,
  setToolDisplayPreference,
  type AssistantMessageDisplayPreference,
  type ToolDisplayPreference,
} from "../utils/chatDisplayPreference";
import { openExternalLink } from "../utils/openExternalLink";
import { getDocsUrl, getFaqUrl, getReleaseNotesUrl } from "./constants";
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
  authEnabled?: boolean;
  onOpenAccount?: () => void;
  onLogout?: () => void;
}

interface FlyoutItemProps {
  icon: ReactNode;
  label: ReactNode;
  content: ReactNode;
}

interface FlyoutContextValue {
  setChildOpen: (id: string, open: boolean) => void;
}

const FlyoutContext = createContext<FlyoutContextValue | null>(null);

function FlyoutItem({ icon, label, content }: FlyoutItemProps) {
  const parentFlyout = useContext(FlyoutContext);
  const flyoutId = useId();
  const [requestedOpen, setRequestedOpen] = useState(false);
  const [openChildIds, setOpenChildIds] = useState<Set<string>>(
    () => new Set(),
  );
  const open = requestedOpen || openChildIds.size > 0;
  const setChildOpen = useCallback((id: string, childOpen: boolean) => {
    setOpenChildIds((current) => {
      if (current.has(id) === childOpen) return current;
      const next = new Set(current);
      if (childOpen) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);
  const contextValue = useMemo(() => ({ setChildOpen }), [setChildOpen]);

  useEffect(() => {
    parentFlyout?.setChildOpen(flyoutId, open);
  }, [flyoutId, open, parentFlyout]);

  useEffect(
    () => () => parentFlyout?.setChildOpen(flyoutId, false),
    [flyoutId, parentFlyout],
  );

  return (
    <Popover
      open={open}
      onOpenChange={setRequestedOpen}
      placement="rightTop"
      trigger={["hover", "click"]}
      content={
        <FlyoutContext.Provider value={contextValue}>
          {content}
        </FlyoutContext.Provider>
      }
      overlayClassName={styles.nestedPopover}
      destroyOnHidden
      mouseEnterDelay={0.06}
      mouseLeaveDelay={0.18}
    >
      <button
        type="button"
        className={styles.menuItem}
        aria-haspopup="menu"
        aria-expanded={open}
      >
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
  authEnabled = false,
  onOpenAccount,
  onLogout,
}: SidebarSettingsPanelProps) {
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
  const [wideMode, setWideMode] = useState(getChatWideModePreference);
  const [showThinking, setShowThinking] = useState(getShowThinkingPreference);
  const [toolDisplayMode, setToolDisplayMode] = useState(
    getToolDisplayPreference,
  );
  const [assistantDisplayMode, setAssistantDisplayMode] = useState(
    getAssistantMessageDisplayPreference,
  );
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

  const toggleThinkingDisplay = () => {
    const show = !showThinking;
    finishAction(() => {
      setShowThinkingPreference(show);
      setShowThinking(show);
    });
  };

  const changeToolDisplay = (mode: ToolDisplayPreference) => {
    finishAction(() => {
      setToolDisplayPreference(mode);
      setToolDisplayMode(mode);
    });
  };

  const changeAssistantDisplay = (mode: AssistantMessageDisplayPreference) => {
    finishAction(() => {
      setAssistantMessageDisplayPreference(mode);
      setAssistantDisplayMode(mode);
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

  const toolDisplayChoices = (
    <ChoicePanel<ToolDisplayPreference>
      choices={[
        {
          value: "current",
          label: t("settingsCenter.toolDisplayCurrent", "Card view"),
        },
        {
          value: "raw-input-output",
          label: t("settingsCenter.toolDisplayRaw", "Raw parameters"),
        },
      ]}
      value={toolDisplayMode}
      onChange={changeToolDisplay}
    />
  );

  const assistantDisplayChoices = (
    <ChoicePanel<AssistantMessageDisplayPreference>
      choices={[
        {
          value: "expanded",
          label: t("settingsCenter.displayExpanded", "Expanded"),
        },
        {
          value: "process-collapsed",
          label: t(
            "settingsCenter.displayProcessCollapsed",
            "Collapse process",
          ),
        },
        {
          value: "result-collapsed",
          label: t("settingsCenter.displayResultCollapsed", "Collapse results"),
        },
      ]}
      value={assistantDisplayMode}
      onChange={changeAssistantDisplay}
    />
  );

  const appearanceContent = (
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

  const messageDisplayContent = (
    <div className={styles.flyoutPanel}>
      <FlyoutItem
        icon={<UnfoldHorizontal size={16} />}
        label={t("settingsCenter.contentWidth", "Message width")}
        content={widthChoices}
      />
      <FlyoutItem
        icon={<ListCollapse size={16} />}
        label={t(
          "settingsCenter.assistantDisplay",
          "Assistant message collapse",
        )}
        content={assistantDisplayChoices}
      />
      <button
        type="button"
        className={styles.menuItem}
        aria-pressed={showThinking}
        onClick={toggleThinkingDisplay}
      >
        <BrainCircuit size={16} />
        <span>{t("settingsCenter.thinkingDisplay", "Show thinking")}</span>
        {showThinking && <Check className={styles.check} size={16} />}
      </button>
      <FlyoutItem
        icon={<Wrench size={16} />}
        label={t("settingsCenter.toolDisplay", "Tool display")}
        content={toolDisplayChoices}
      />
    </div>
  );

  return (
    <div className={styles.panel}>
      <FlyoutItem
        icon={<Palette size={16} />}
        label={t("sidebar.quickMenu.appearance", "Appearance")}
        content={appearanceContent}
      />
      <FlyoutItem
        icon={<MessageSquareText size={16} />}
        label={t("settingsCenter.chatDisplay", "Message display")}
        content={messageDisplayContent}
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

      {authEnabled && (
        <>
          <div className={styles.divider} />
          <button
            type="button"
            className={styles.menuItem}
            onClick={() => onOpenAccount && finishAction(onOpenAccount)}
          >
            <UserRound size={16} />
            <span>{t("account.title", "Account")}</span>
          </button>
          <button
            type="button"
            className={`${styles.menuItem} ${styles.dangerItem}`}
            onClick={() => onLogout && finishAction(onLogout)}
          >
            <LogOut size={16} />
            <span>{t("login.logout", "Logout")}</span>
          </button>
        </>
      )}
    </div>
  );
}
