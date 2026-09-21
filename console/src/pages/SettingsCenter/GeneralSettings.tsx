import {
  App,
  Button,
  ColorPicker,
  Input,
  Segmented,
  Select,
  Slider,
  Switch,
} from "antd";
import {
  BrainCircuit,
  Expand,
  Languages,
  MessageSquareText,
  Monitor,
  Palette,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { LANGUAGE_LIST } from "@/constants/languageList";
import { useTheme, type ThemeMode } from "@/contexts/ThemeContext";
import type { ThemeConfig } from "@/api/modules/theme";
import { isTauriRuntime } from "@/tauri/backendRuntime";
import {
  clearRememberedCloseAction,
  getRememberedCloseAction,
  setRememberedCloseAction,
  type CloseAction,
} from "@/tauri/closeWindowPreference";
import { applyLanguagePreference } from "@/utils/languagePreference";
import {
  DEFAULT_CONSOLE_TITLE,
  setConsoleTitlePreference,
  useConsoleTitlePreference,
} from "@/utils/consoleTitlePreference";
import { getOsRootHref } from "@/utils/navigationMode";
import {
  getChatWideModePreference,
  setChatWideModePreference,
} from "@/utils/chatLayoutPreference";
import {
  getAssistantMessageDisplayPreference,
  getShowThinkingPreference,
  getToolDisplayPreference,
  setAssistantMessageDisplayPreference,
  setShowThinkingPreference,
  setToolDisplayPreference,
  type AssistantMessageDisplayPreference,
  type ToolDisplayPreference,
} from "@/utils/chatDisplayPreference";
import {
  applyThemePreset,
  DEFAULT_THEME_PRESET,
  getThemePresetId,
  THEME_PRESETS,
  type ThemePreset,
} from "./themePresets";
import styles from "./index.module.less";

type CloseBehavior = "ask" | CloseAction;
type ContentWidth = "standard" | "wide";

const LANGUAGES = LANGUAGE_LIST.map(({ key, label }) => ({
  value: key,
  label,
}));

function ThemePresetLabel({ preset }: { preset: ThemePreset }) {
  const { isDark } = useTheme();

  return (
    <span className={styles.themePresetOption}>
      <span
        aria-hidden="true"
        className={styles.themePresetSwatch}
        style={{
          background: isDark
            ? preset.theme.dark?.surface ?? "#1f1f1f"
            : "#ffffff",
          color: isDark
            ? preset.theme.dark?.accent ?? preset.theme.accent
            : preset.theme.accent,
        }}
      >
        Aa
      </span>
      <span>{preset.name}</span>
    </span>
  );
}

export default function GeneralSettings() {
  const { t, i18n } = useTranslation();
  const {
    themeMode,
    setThemeMode,
    userTheme,
    previewTheme,
    setThemePreview,
    saveUserTheme,
    resetUserTheme,
  } = useTheme();
  const { message } = App.useApp();
  const consoleTitle = useConsoleTitlePreference();
  const [draftTheme, setDraftTheme] = useState<ThemeConfig>(previewTheme);
  const [savingTheme, setSavingTheme] = useState(false);
  const [wideMode, setWideMode] = useState(getChatWideModePreference);
  const [toolDisplayMode, setToolDisplayMode] = useState(
    getToolDisplayPreference,
  );
  const [assistantDisplayMode, setAssistantDisplayMode] = useState(
    getAssistantMessageDisplayPreference,
  );
  const [showThinking, setShowThinking] = useState(getShowThinkingPreference);
  const rawLanguage = i18n.resolvedLanguage || i18n.language || "en";
  const currentLanguage = LANGUAGES.some(
    (language) => language.value === rawLanguage,
  )
    ? rawLanguage
    : rawLanguage.split("-")[0];
  const closeBehavior = isTauriRuntime()
    ? getRememberedCloseAction() ?? "ask"
    : "ask";

  useEffect(() => {
    setDraftTheme(previewTheme);
  }, [previewTheme]);

  const updateDraftTheme = (patch: Partial<ThemeConfig>) => {
    const next = { ...draftTheme, ...patch };
    setDraftTheme(next);
    setThemePreview(next);
  };

  const updateDarkTheme = (patch: NonNullable<ThemeConfig["dark"]>) => {
    updateDraftTheme({ dark: { ...draftTheme.dark, ...patch } });
  };

  const selectThemePreset = (presetId: string) => {
    const next = applyThemePreset(draftTheme, presetId);
    setDraftTheme(next);
    setThemePreview(next);
  };

  const saveTheme = async () => {
    setSavingTheme(true);
    try {
      await saveUserTheme(draftTheme);
      message.success(t("settingsCenter.themeSaved", "Theme saved"));
    } catch {
      setThemePreview(userTheme);
      setDraftTheme(userTheme);
      message.error(
        t("settingsCenter.themeSaveFailed", "Failed to save theme"),
      );
    } finally {
      setSavingTheme(false);
    }
  };

  const resetTheme = async () => {
    setSavingTheme(true);
    try {
      await resetUserTheme();
      setDraftTheme({});
      message.success(t("settingsCenter.themeReset", "Theme reset"));
    } catch {
      setThemePreview(userTheme);
      setDraftTheme(userTheme);
      message.error(
        t("settingsCenter.themeSaveFailed", "Failed to save theme"),
      );
    } finally {
      setSavingTheme(false);
    }
  };

  const changeLanguage = (language: string) => {
    applyLanguagePreference(i18n, language, {
      onPersistError: () => message.error(t("agentConfig.languageSaveFailed")),
    });
  };

  const changeConsoleTitle = (title: string) => {
    try {
      setConsoleTitlePreference(title);
    } catch {
      message.error(t("settingsCenter.browserTitleSaveFailed"));
    }
  };

  const changeCloseBehavior = (value: CloseBehavior) => {
    if (value === "ask") clearRememberedCloseAction();
    else setRememberedCloseAction(value);
  };

  const changeContentWidth = (width: ContentWidth) => {
    const enabled = width === "wide";
    setChatWideModePreference(enabled);
    setWideMode(enabled);
  };

  const changeToolDisplayMode = (mode: ToolDisplayPreference) => {
    setToolDisplayPreference(mode);
    setToolDisplayMode(mode);
  };

  const changeAssistantDisplayMode = (
    mode: AssistantMessageDisplayPreference,
  ) => {
    setAssistantMessageDisplayPreference(mode);
    setAssistantDisplayMode(mode);
  };

  const changeShowThinking = (show: boolean) => {
    setShowThinkingPreference(show);
    setShowThinking(show);
  };

  return (
    <div className={styles.preferencePage}>
      <div className={styles.pageTitle}>
        <h2>{t("settingsCenter.pages.general", "General")}</h2>
      </div>

      <section className={styles.settingsSection}>
        <h3 className={styles.sectionTitle}>
          {t("settingsCenter.appearanceAndLanguage", "Appearance & language")}
        </h3>
        <div className={styles.settingsCard}>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <Monitor size={18} />
            </span>
            <span className={styles.settingCopy}>
              <label htmlFor="console-browser-title">
                <strong>{t("settingsCenter.browserTitle")}</strong>
              </label>
              <small>{t("settingsCenter.browserTitleHint")}</small>
            </span>
            <Input
              id="console-browser-title"
              className={styles.settingControl}
              value={consoleTitle}
              placeholder={DEFAULT_CONSOLE_TITLE}
              allowClear
              onChange={(event) => changeConsoleTitle(event.target.value)}
            />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <Languages size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>{t("sidebar.settings.language")}</strong>
              <small>
                {t(
                  "settingsCenter.languageHint",
                  "Changes the interface language on this device.",
                )}
              </small>
            </span>
            <Select
              className={styles.settingControl}
              value={currentLanguage}
              options={LANGUAGES}
              onChange={changeLanguage}
            />
          </div>

          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <Palette size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>{t("sidebar.settings.theme")}</strong>
              <small>
                {t(
                  "settingsCenter.themeHint",
                  "Use a light, dark or system-matched appearance.",
                )}
              </small>
            </span>
            <Segmented<ThemeMode>
              className={styles.segmentedControl}
              value={themeMode}
              options={[
                { value: "light", label: t("theme.light") },
                { value: "dark", label: t("theme.dark") },
                { value: "system", label: t("theme.system") },
              ]}
              onChange={setThemeMode}
            />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <Monitor size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>{t("sidebar.settings.desktopMode")}</strong>
              <small>
                {t(
                  "settingsCenter.desktopModeHint",
                  "Open the multi-window desktop workspace.",
                )}
              </small>
            </span>
            <Button
              onClick={() =>
                window.location.assign(getOsRootHref(window.location.pathname))
              }
            >
              {t("settingsCenter.open", "Open")}
            </Button>
          </div>
          <div className={styles.themeEditor}>
            <div className={styles.themeEditorHeader}>
              <span className={styles.settingIcon}>
                <Palette size={18} />
              </span>
              <span className={styles.settingCopy}>
                <strong>
                  {t("settingsCenter.customTheme", "Custom theme")}
                </strong>
                <small>
                  {t(
                    "settingsCenter.customThemeHint",
                    "Choose a color palette or fine-tune it for the console.",
                  )}
                </small>
              </span>
              <div className={styles.themeActions}>
                <Button
                  onClick={() => void resetTheme()}
                  disabled={savingTheme}
                >
                  {t("common.reset", "Reset")}
                </Button>
                <Button
                  type="primary"
                  onClick={() => void saveTheme()}
                  loading={savingTheme}
                >
                  {t("common.save", "Save")}
                </Button>
              </div>
            </div>
            <div className={styles.themeFields}>
              <label
                className={`${styles.themeField} ${styles.themePresetField}`}
              >
                <span>{t("settingsCenter.themePalette", "Theme palette")}</span>
                <Select
                  aria-label={t("settingsCenter.themePalette", "Theme palette")}
                  value={getThemePresetId(draftTheme)}
                  placeholder={t("settingsCenter.customTheme", "Custom theme")}
                  options={THEME_PRESETS.map((preset) => ({
                    value: preset.id,
                    label: <ThemePresetLabel preset={preset} />,
                  }))}
                  onChange={selectThemePreset}
                />
              </label>
              <label className={styles.themeField}>
                <span>{t("settingsCenter.accentColor", "Accent color")}</span>
                <ColorPicker
                  value={draftTheme.accent ?? DEFAULT_THEME_PRESET.theme.accent}
                  showText
                  onChange={(_, hex) => updateDraftTheme({ accent: hex })}
                />
              </label>
              <label className={styles.themeField}>
                <span>{t("settingsCenter.accentHover", "Accent hover")}</span>
                <ColorPicker
                  value={
                    draftTheme.accent_hover ??
                    DEFAULT_THEME_PRESET.theme.accent_hover
                  }
                  showText
                  onChange={(_, hex) => updateDraftTheme({ accent_hover: hex })}
                />
              </label>
              <label className={styles.themeField}>
                <span>
                  {t("settingsCenter.accentBackground", "Accent background")}
                </span>
                <Input
                  value={
                    draftTheme.accent_bg ??
                    DEFAULT_THEME_PRESET.theme.accent_bg ??
                    ""
                  }
                  placeholder="rgba(255, 127, 22, 0.1)"
                  onChange={(event) =>
                    updateDraftTheme({
                      accent_bg: event.target.value || undefined,
                    })
                  }
                />
              </label>
              <label className={styles.themeField}>
                <span>
                  {t("settingsCenter.cornerRadius", "Corner radius")}
                  <output>{draftTheme.radius ?? "8px"}</output>
                </span>
                <Slider
                  min={0}
                  max={20}
                  value={Number.parseFloat(draftTheme.radius ?? "8")}
                  onChange={(value) =>
                    updateDraftTheme({ radius: `${value}px` })
                  }
                />
              </label>
              <label className={styles.themeField}>
                <span>
                  {t("settingsCenter.darkAccentColor", "Dark accent")}
                </span>
                <ColorPicker
                  value={
                    draftTheme.dark?.accent ??
                    DEFAULT_THEME_PRESET.theme.dark?.accent
                  }
                  showText
                  onChange={(_, hex) => updateDarkTheme({ accent: hex })}
                />
              </label>
              <label className={styles.themeField}>
                <span>{t("settingsCenter.darkSurface", "Dark surface")}</span>
                <Input
                  value={
                    draftTheme.dark?.surface ??
                    DEFAULT_THEME_PRESET.theme.dark?.surface ??
                    ""
                  }
                  placeholder="#1a1a1a"
                  onChange={(event) =>
                    updateDarkTheme({
                      surface: event.target.value || undefined,
                    })
                  }
                />
              </label>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.settingsSection}>
        <h3 className={styles.sectionTitle}>
          {t("settingsCenter.chatDisplay", "Message display")}
        </h3>
        <div className={styles.settingsCard}>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <Expand size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>
                {t("settingsCenter.contentWidth", "Message width")}
              </strong>
              <small>
                {t(
                  "settingsCenter.contentWidthHint",
                  "Choose the standard or wide conversation width.",
                )}
              </small>
            </span>
            <Segmented<ContentWidth>
              className={styles.segmentedControl}
              aria-label={t("settingsCenter.contentWidth", "Message width")}
              value={wideMode ? "wide" : "standard"}
              options={[
                {
                  value: "standard",
                  label: t("settingsCenter.contentWidthStandard", "Standard"),
                },
                {
                  value: "wide",
                  label: t("settingsCenter.contentWidthWide", "Wide"),
                },
              ]}
              onChange={changeContentWidth}
            />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <MessageSquareText size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>
                {t(
                  "settingsCenter.assistantDisplay",
                  "Assistant message collapse",
                )}
              </strong>
              <small>
                {t(
                  "settingsCenter.assistantDisplayHint",
                  "Control how intermediate text, reasoning and tools collapse.",
                )}
              </small>
            </span>
            <Segmented<AssistantMessageDisplayPreference>
              className={styles.messageDisplayControl}
              value={assistantDisplayMode}
              options={[
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
                  label: t(
                    "settingsCenter.displayResultCollapsed",
                    "Collapse results",
                  ),
                },
              ]}
              onChange={changeAssistantDisplayMode}
            />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <BrainCircuit size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>
                {t("settingsCenter.thinkingDisplay", "Show thinking")}
              </strong>
              <small>
                {t(
                  "settingsCenter.thinkingDisplayHint",
                  "Show model reasoning in conversations without changing model behavior.",
                )}
              </small>
            </span>
            <Switch checked={showThinking} onChange={changeShowThinking} />
          </div>
          <div className={styles.settingRow}>
            <span className={styles.settingIcon}>
              <Wrench size={18} />
            </span>
            <span className={styles.settingCopy}>
              <strong>{t("settingsCenter.toolDisplay", "Tool display")}</strong>
              <small>
                {t(
                  "settingsCenter.toolDisplayHint",
                  "Choose what appears after opening a tool card.",
                )}
              </small>
            </span>
            <Segmented<ToolDisplayPreference>
              className={styles.segmentedControl}
              value={toolDisplayMode}
              options={[
                {
                  value: "current",
                  label: t("settingsCenter.toolDisplayCurrent", "Card view"),
                },
                {
                  value: "raw-input-output",
                  label: t("settingsCenter.toolDisplayRaw", "Raw parameters"),
                },
              ]}
              onChange={changeToolDisplayMode}
            />
          </div>
        </div>
      </section>

      {isTauriRuntime() && (
        <section className={styles.settingsSection}>
          <h3 className={styles.sectionTitle}>
            {t("settingsCenter.desktopApplication", "Desktop app")}
          </h3>
          <div className={styles.settingsCard}>
            <div className={styles.settingRow}>
              <span className={styles.settingIcon}>
                <Monitor size={18} />
              </span>
              <span className={styles.settingCopy}>
                <strong>{t("desktop.closeWindow.preference")}</strong>
                <small>
                  {t(
                    "settingsCenter.closeBehaviorHint",
                    "Choose what happens when the desktop window closes.",
                  )}
                </small>
              </span>
              <Select<CloseBehavior>
                className={styles.settingControl}
                defaultValue={closeBehavior}
                onChange={changeCloseBehavior}
                options={[
                  {
                    value: "ask",
                    label: t("desktop.closeWindow.askEveryTime"),
                  },
                  {
                    value: "minimize-to-tray",
                    label: t("desktop.closeWindow.minimizeToTray"),
                  },
                  {
                    value: "quit",
                    label: t("desktop.closeWindow.quitApp"),
                  },
                ]}
              />
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
