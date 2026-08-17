import React from "react";
import { useTranslation } from "react-i18next";

import { Monitor, SunMoon } from "lucide-react";
import { Select } from "antd";
import {
  SparkSunLine,
  SparkMoonLine,
  SparkFullscreenLine,
  SparkExitFullscreenLine,
} from "@agentscope-ai/icons";
import { LANGUAGE_LIST } from "../components/LanguageSwitcher";
import { settingsApi } from "../api/modules/language";
import { useTheme, type ThemeMode } from "../contexts/ThemeContext";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import { isTauriRuntime } from "../tauri/backendRuntime";
import {
  clearRememberedCloseAction,
  getRememberedCloseAction,
  setRememberedCloseAction,
  type CloseAction,
} from "../tauri/closeWindowPreference";
import styles from "./sidebarSettingsPanel.module.less";
import { getOsRootHref } from "../utils/navigationMode";

type CloseBehavior = "ask" | CloseAction;

// ── Language config ────────────────────────────────────────────────────────
// Reuse the shared list from the top-right language dropdown (Header /
// LanguageSwitcher) so both selectors always offer the same set of languages.
const KNOWN_KEYS = new Set(LANGUAGE_LIST.map((l) => l.key));

// ── Component ─────────────────────────────────────────────────────────────

interface SidebarSettingsPanelProps {
  onClose?: () => void;
}

export default function SidebarSettingsPanel({
  onClose,
}: SidebarSettingsPanelProps) {
  const { t, i18n } = useTranslation();
  const { themeMode, setThemeMode } = useTheme();
  const { mode: sidebarMode, toggleMode: toggleSidebarMode } =
    useSidebarModeStore();
  const [closeBehavior, setCloseBehavior] = React.useState<CloseBehavior>(() =>
    isTauriRuntime() ? getRememberedCloseAction() ?? "ask" : "ask",
  );

  const raw = i18n.resolvedLanguage || i18n.language;
  const currentLang = KNOWN_KEYS.has(raw) ? raw : raw.split("-")[0];

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
    settingsApi.updateLanguage(lang).catch(() => {});
  };

  const changeCloseBehavior = (value: CloseBehavior) => {
    if (value === "ask") {
      clearRememberedCloseAction();
    } else {
      setRememberedCloseAction(value);
    }
    setCloseBehavior(value);
  };

  const themeOptions: {
    key: ThemeMode;
    label: string;
    icon: React.ReactNode;
  }[] = [
    {
      key: "light",
      label: t("theme.light", "Light"),
      icon: <SparkSunLine size={14} />,
    },
    {
      key: "dark",
      label: t("theme.dark", "Dark"),
      icon: <SparkMoonLine size={14} />,
    },
    {
      key: "system",
      label: t("theme.system", "System"),
      icon: <SunMoon size={14} />,
    },
  ];

  return (
    <div className={styles.panel}>
      {/* ── Language ─────────────────────────────────────── */}
      <div className={styles.row}>
        <span className={styles.label}>
          {t("sidebar.settings.language", "Language")}
        </span>
        <div className={styles.options}>
          {LANGUAGE_LIST.map(({ key, label, icon }) => (
            <button
              key={key}
              title={label}
              className={`${styles.optBtn} ${
                currentLang === key ? styles.optBtnActive : ""
              }`}
              onClick={() => changeLanguage(key)}
            >
              {React.cloneElement(icon, { size: 14 })}
            </button>
          ))}
        </div>
      </div>

      {/* ── Theme ────────────────────────────────────────── */}
      <div className={styles.row}>
        <span className={styles.label}>
          {t("sidebar.settings.theme", "Theme")}
        </span>
        <div className={styles.options}>
          {themeOptions.map(({ key, label, icon }) => (
            <button
              key={key}
              title={label}
              className={`${styles.optBtn} ${
                themeMode === key ? styles.optBtnActive : ""
              }`}
              onClick={() => setThemeMode(key)}
            >
              {icon}
              <span className={styles.optLabel}>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Close Window (desktop only) ──────────────────── */}
      {isTauriRuntime() ? (
        <div className={styles.row}>
          <span className={styles.label}>
            {t("desktop.closeWindow.preference", "Close Window")}
          </span>
          <Select<CloseBehavior>
            size="small"
            style={{ width: "100%" }}
            value={closeBehavior}
            onChange={changeCloseBehavior}
            options={[
              {
                value: "ask",
                label: t("desktop.closeWindow.askEveryTime", "Ask every time"),
              },
              {
                value: "minimize-to-tray",
                label: t(
                  "desktop.closeWindow.minimizeToTray",
                  "Minimize to Tray",
                ),
              },
              {
                value: "quit",
                label: t("desktop.closeWindow.quitApp", "Quit App"),
              },
            ]}
          />
        </div>
      ) : null}

      {/* ── Mode ─────────────────────────────────────────── */}
      <div className={styles.row}>
        <span className={styles.label}>
          {t("sidebar.settings.mode", "Mode")}
        </span>
        <div className={styles.modeActions}>
          <button
            className={`${styles.optBtn} ${styles.optBtnBlock}`}
            onClick={() => {
              toggleSidebarMode();
              onClose?.();
            }}
          >
            {sidebarMode === "simple" ? (
              <>
                <SparkFullscreenLine size={14} />
                <span className={styles.optLabel}>
                  {t("sidebar.fullMode", "Full Mode")}
                </span>
              </>
            ) : (
              <>
                <SparkExitFullscreenLine size={14} />
                <span className={styles.optLabel}>
                  {t("sidebar.simpleMode", "Simple Mode")}
                </span>
              </>
            )}
          </button>
          <button
            className={`${styles.optBtn} ${styles.optBtnBlock} ${styles.desktopModeBtn}`}
            onClick={() => {
              onClose?.();
              window.location.assign(getOsRootHref(window.location.pathname));
            }}
          >
            <Monitor size={14} />
            <span className={styles.optLabel}>
              {t("sidebar.settings.desktopMode", "Desktop Mode")}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
