import { Button, Segmented, Select, Switch } from "antd";
import { Expand, Monitor, Palette, Languages } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { languageApi } from "@/api/modules/language";
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
import styles from "./index.module.less";

type CloseBehavior = "ask" | CloseAction;

const LANGUAGES = [
  { value: "zh", label: "简体中文" },
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
  { value: "ru", label: "Русский" },
  { value: "id", label: "Bahasa Indonesia" },
  { value: "vi", label: "Tiếng Việt" },
  { value: "pt-BR", label: "Português" },
];

export default function GeneralSettings() {
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
  const [wideMode, setWideMode] = useState(getChatWideModePreference);
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
    void languageApi.updateLanguage(language).catch(() => {});
  };

  const changeCloseBehavior = (value: CloseBehavior) => {
    if (value === "ask") clearRememberedCloseAction();
    else setRememberedCloseAction(value);
  };

  const changeWideMode = (enabled: boolean) => {
    setChatWideModePreference(enabled);
    setWideMode(enabled);
  };

  return (
    <div className={styles.preferencePage}>
      <div className={styles.pageTitle}>
        <h2>{t("settingsCenter.pages.general", "General")}</h2>
        <p>
          {t(
            "settingsCenter.generalDescription",
            "Language, appearance and application behavior apply immediately.",
          )}
        </p>
      </div>

      <section className={styles.settingsCard}>
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
            className={styles.settingControl}
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
            <Expand size={18} />
          </span>
          <span className={styles.settingCopy}>
            <strong>{t("settingsCenter.wideMode", "Wide mode")}</strong>
            <small>
              {t(
                "settingsCenter.wideModeHint",
                "Use the available page width for conversations.",
              )}
            </small>
          </span>
          <Switch
            aria-label={t("settingsCenter.wideMode", "Wide mode")}
            checked={wideMode}
            onChange={changeWideMode}
          />
        </div>
      </section>

      {isTauriRuntime() && (
        <section className={styles.settingsCard}>
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
        </section>
      )}
    </div>
  );
}
