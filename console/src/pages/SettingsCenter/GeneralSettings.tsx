import { useAutoSave } from "@/hooks/useAutoSave";
import {
  App,
  Button,
  ColorPicker,
  Input,
  Grid,
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
  Sun,
  Moon,
  Check,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useState, useId } from "react";
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
import sliderStyles from "@/components/interaction/NumberSlider.module.less";
import NavigationSettings from "./NavigationSettings";
import baseStyles from "./index.module.less";
import polish from "./GeneralSettings.module.less";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { RunningGlow } from "@/components/interaction/RunningGlow";
import { Cascade } from "@/components/interaction/Cascade";
import { SharedModal } from "@/components/interaction/SharedModal";
import BottomSheet from "@/components/interaction/BottomSheet";

const styles = { ...baseStyles, ...polish };

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
  const [editorOpen, setEditorOpen] = useState(false);
  const screens = Grid.useBreakpoint();
  const mobile = screens.md === false;
  const surfaceId = useId();
  const reduced = useReducedMotion();
  const closeEditor = () => {
    void flushTheme();
    setEditorOpen(false);
  };
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
    scheduleTheme();
  };

  const updateDarkTheme = (patch: NonNullable<ThemeConfig["dark"]>) => {
    updateDraftTheme({ dark: { ...draftTheme.dark, ...patch } });
  };

  const selectThemePreset = (presetId: string) => {
    const next = applyThemePreset(draftTheme, presetId);
    setDraftTheme(next);
    setThemePreview(next);
    scheduleTheme();
  };

  const { schedule: scheduleTheme, flush: flushTheme } = useAutoSave(
    async () => {
      await saveUserTheme(draftTheme);
    },
  );

  const resetTheme = async () => {
    await flushTheme();
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

  const themeEditor = (
    <div className={styles.themeEditor}>
      <div className={styles.themeEditorHeader}>
        <span className={styles.settingIcon}>
          <Palette size={18} />
        </span>
        <span className={styles.settingCopy}>
          <strong>{t("settingsCenter.customTheme", "Custom theme")}</strong>
        </span>
        <div className={styles.themeActions}>
          <Button onClick={() => void resetTheme()} disabled={savingTheme}>
            {t("common.reset", "Reset")}
          </Button>
        </div>
      </div>
      <div className={styles.themeFields}>
        <label className={`${styles.themeField} ${styles.themePresetField}`}>
          <span>{t("settingsCenter.themePalette", "Theme palette")}</span>
          <Select
            aria-label={t("settingsCenter.themePalette", "Theme palette")}
            getPopupContainer={(trigger) => trigger.parentElement!}
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
            getPopupContainer={(trigger) => trigger.parentElement!}
            value={draftTheme.accent ?? DEFAULT_THEME_PRESET.theme.accent}
            showText
            onChange={(_, hex) => updateDraftTheme({ accent: hex })}
          />
        </label>
        <label className={styles.themeField}>
          <span>{t("settingsCenter.accentHover", "Accent hover")}</span>
          <ColorPicker
            getPopupContainer={(trigger) => trigger.parentElement!}
            value={
              draftTheme.accent_hover ?? DEFAULT_THEME_PRESET.theme.accent_hover
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
              draftTheme.accent_bg ?? DEFAULT_THEME_PRESET.theme.accent_bg ?? ""
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
            <output>
              <NumberFlow
                value={Number.parseFloat(draftTheme.radius ?? "8")}
                suffix="px"
                animated={!reduced}
              />
            </output>
          </span>
          <div className={sliderStyles.control}>
            <Slider
              aria-label={t("settingsCenter.cornerRadius", "Corner radius")}
              min={0}
              max={20}
              value={Number.parseFloat(draftTheme.radius ?? "8")}
              onChange={(value) => updateDraftTheme({ radius: `${value}px` })}
              style={{ flex: 1 }}
            />
          </div>
        </label>
        <label className={styles.themeField}>
          <span>{t("settingsCenter.darkAccentColor", "Dark accent")}</span>
          <ColorPicker
            getPopupContainer={(trigger) => trigger.parentElement!}
            value={
              draftTheme.dark?.accent ?? DEFAULT_THEME_PRESET.theme.dark?.accent
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
  );

  return (
    <LayoutGroup id={surfaceId}>
      <div className={styles.preferencePage}>
        <div className={styles.pageTitle}>
          <h2>{t("settingsCenter.pages.general", "General")}</h2>
        </div>

        <section className={styles.settingsSection}>
          <Cascade>
            <h3 className={styles.sectionTitle}>
              {t(
                "settingsCenter.appearanceAndLanguage",
                "Appearance & language",
              )}
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
                <div
                  className={styles.appearanceChoices}
                  role="group"
                  aria-label={t("sidebar.settings.theme")}
                >
                  {(["light", "dark", "system"] as ThemeMode[]).map((mode) => {
                    const Icon =
                      mode === "light" ? Sun : mode === "dark" ? Moon : Monitor;
                    return (
                      <InteractiveCard key={mode} tilt={2}>
                        <button
                          className={styles.appearanceChoice}
                          data-mode={mode}
                          data-press
                          aria-pressed={themeMode === mode}
                          onClick={() => setThemeMode(mode)}
                        >
                          <span
                            className={styles.miniWindow}
                            aria-hidden="true"
                          >
                            <span className={styles.miniSidebar}>
                              <i />
                              <i />
                              <i />
                            </span>
                            <span className={styles.miniChat}>
                              <i />
                              <i />
                              <i />
                            </span>
                          </span>
                          <span className={styles.modeLabel}>
                            <Icon size={16} />
                            {t(`theme.${mode}`)}
                            {themeMode === mode && <Check size={14} />}
                          </span>
                          <RunningGlow active={themeMode === mode} />
                        </button>
                      </InteractiveCard>
                    );
                  })}
                </div>
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
                    window.location.assign(
                      getOsRootHref(window.location.pathname),
                    )
                  }
                >
                  {t("settingsCenter.open", "Open")}
                </Button>
              </div>
              <div className={styles.customRow}>
                <span className={styles.paletteDots} aria-hidden="true">
                  {THEME_PRESETS.slice(0, 5).map((preset) => (
                    <i
                      key={preset.id}
                      style={{ background: preset.theme.accent }}
                    />
                  ))}
                </span>
                <motion.button
                  className={styles.customButton}
                  style={{ borderRadius: 24 }}
                  whileTap={reduced ? undefined : { scale: 0.96 }}
                  transition={{ type: "spring", stiffness: 420, damping: 28 }}
                  layoutId={reduced || mobile ? undefined : surfaceId}
                  onClick={() => setEditorOpen(true)}
                  aria-haspopup="dialog"
                  aria-expanded={editorOpen}
                >
                  <SlidersHorizontal size={16} />
                  {t("settingsCenter.customTheme", "Custom theme")}
                </motion.button>
              </div>
            </div>
          </Cascade>
        </section>

        <section className={styles.settingsSection}>
          <NavigationSettings />
        </section>

        <section className={styles.settingsSection}>
          <Cascade index={1}>
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
                      label: t(
                        "settingsCenter.contentWidthStandard",
                        "Standard",
                      ),
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
                <Switch
                  aria-label={t(
                    "settingsCenter.thinkingDisplay",
                    "Show thinking",
                  )}
                  checked={showThinking}
                  onChange={changeShowThinking}
                />
              </div>
              <div className={styles.settingRow}>
                <span className={styles.settingIcon}>
                  <Wrench size={18} />
                </span>
                <span className={styles.settingCopy}>
                  <strong>
                    {t("settingsCenter.toolDisplay", "Tool display")}
                  </strong>
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
                      label: t(
                        "settingsCenter.toolDisplayCurrent",
                        "Card view",
                      ),
                    },
                    {
                      value: "raw-input-output",
                      label: t(
                        "settingsCenter.toolDisplayRaw",
                        "Raw parameters",
                      ),
                    },
                  ]}
                  onChange={changeToolDisplayMode}
                />
              </div>
            </div>
          </Cascade>
        </section>

        {isTauriRuntime() && (
          <section className={styles.settingsSection}>
            <Cascade index={2}>
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
            </Cascade>
          </section>
        )}
      </div>
      {mobile ? (
        <BottomSheet
          open={editorOpen}
          onOpenChange={(open) => {
            if (!open) closeEditor();
          }}
          title={t("settingsCenter.customTheme", "Custom theme")}
          tall
        >
          {themeEditor}
        </BottomSheet>
      ) : (
        <SharedModal
          open={editorOpen}
          onCancel={closeEditor}
          surfaceId={surfaceId}
          title={t("settingsCenter.customTheme", "Custom theme")}
          footer={null}
          width={640}
          centered
          maskClosable={!savingTheme}
          closable={!savingTheme}
        >
          {themeEditor}
        </SharedModal>
      )}
    </LayoutGroup>
  );
}
