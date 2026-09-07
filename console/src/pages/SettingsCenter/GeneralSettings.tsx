import { Button, Segmented, Select, Switch } from "antd";
import {
  BrainCircuit,
  Expand,
  Languages,
  MessageSquareText,
  Monitor,
  Palette,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { settingsApi } from "@/api/modules/language";
import { LANGUAGE_LIST } from "@/constants/languageList";
import { useTheme, type ThemeMode } from "@/contexts/ThemeContext";
import { isTauriRuntime } from "@/tauri/backendRuntime";
import {
  clearRememberedCloseAction,
  getRememberedCloseAction,
  setRememberedCloseAction,
  type CloseAction,
} from "@/tauri/closeWindowPreference";
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
import styles from "./index.module.less";

type CloseBehavior = "ask" | CloseAction;
type ContentWidth = "standard" | "wide";

const LANGUAGES = LANGUAGE_LIST.map(({ key, label }) => ({
  value: key,
  label,
}));

export default function GeneralSettings() {
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
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

  const changeLanguage = (language: string) => {
    void i18n.changeLanguage(language);
    localStorage.setItem("language", language);
    void settingsApi.updateLanguage(language).catch(() => {});
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
