import React from "react";
import { useTranslation } from "react-i18next";

import { SunMoon } from "lucide-react";
import {
  SparkSunLine,
  SparkMoonLine,
  SparkChinese02Line,
  SparkEnglish02Line,
  SparkJapanLine,
  SparkRusLine,
  SparkPtLine,
  SparkFullscreenLine,
  SparkExitFullscreenLine,
} from "@agentscope-ai/icons";
import { languageApi } from "../api/modules/language";
import { useTheme, type ThemeMode } from "../contexts/ThemeContext";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import styles from "./sidebarSettingsPanel.module.less";

// ── Language config ────────────────────────────────────────────────────────

const LANGS = [
  { key: "en", label: "English", icon: <SparkEnglish02Line size={14} /> },
  { key: "zh", label: "简体中文", icon: <SparkChinese02Line size={14} /> },
  { key: "ja", label: "日本語", icon: <SparkJapanLine size={14} /> },
  { key: "ru", label: "Русский", icon: <SparkRusLine size={14} /> },
  { key: "pt-BR", label: "Português", icon: <SparkPtLine size={14} /> },
];
const KNOWN_KEYS = new Set(LANGS.map((l) => l.key));

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

  const raw = i18n.resolvedLanguage || i18n.language;
  const currentLang = KNOWN_KEYS.has(raw) ? raw : raw.split("-")[0];

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
    languageApi.updateLanguage(lang).catch(() => {});
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
          {LANGS.map(({ key, label, icon }) => (
            <button
              key={key}
              title={label}
              className={`${styles.optBtn} ${
                currentLang === key ? styles.optBtnActive : ""
              }`}
              onClick={() => changeLanguage(key)}
            >
              {icon}
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

      {/* ── Mode ─────────────────────────────────────────── */}
      <div className={styles.row}>
        <span className={styles.label}>
          {t("sidebar.settings.mode", "Mode")}
        </span>
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
      </div>
    </div>
  );
}
