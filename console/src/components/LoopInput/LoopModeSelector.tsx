import {
  Boxes,
  ChevronDown,
  CircleDot,
  LoaderCircle,
  MessageCircleQuestion,
  Rocket,
  Settings2,
  Sparkles,
  Target,
} from "lucide-react";
import { Popover, Tooltip } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import {
  DEFAULT_LOOP_MODE,
  fetchAvailableLoopModes,
  type LoopModeInfo,
  useLoopStore,
} from "../../stores/loopStore";
import { InlineMarkdown } from "../Markdown/InlineMarkdown";
import {
  resolveLoopModeDescriptionMarkdown,
  resolveLoopModeName,
} from "../../utils/loopModeDescription";
import styles from "./index.module.less";

function ModeIcon({ mode, size = 14 }: { mode: LoopModeInfo; size?: number }) {
  if (mode.id === "goal") return <Target size={size} />;
  if (mode.id === "mission") return <Rocket size={size} />;
  if (mode.source === "custom") return <Sparkles size={size} />;
  if (mode.source === "plugin") return <Boxes size={size} />;
  return <CircleDot size={size} />;
}

export function LoopModeSelector() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "en";
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const availableModes = useLoopStore((state) => state.availableModes);
  const selectedModeId = useLoopStore((state) => state.selectedModeId);
  const sessionState = useLoopStore((state) => state.sessionState);
  const activeMode = useLoopStore((state) => state.activeMode);
  const catalogLoading = useLoopStore((state) => state.catalogLoading);
  const catalogError = useLoopStore((state) => state.catalogError);
  const setSelectedMode = useLoopStore((state) => state.setSelectedMode);

  const selectedMode =
    availableModes.find((mode) => mode.id === selectedModeId) ??
    DEFAULT_LOOP_MODE;
  const builtInModes = useMemo(
    () => availableModes.filter((mode) => mode.source === "builtin"),
    [availableModes],
  );
  const extendedModes = useMemo(
    () => availableModes.filter((mode) => mode.source !== "builtin"),
    [availableModes],
  );

  if (sessionState !== "idle" && activeMode) {
    const tooltip =
      activeMode.source === "custom"
        ? t("loop.activeCustomDescription")
        : t("loop.activePersistentDescription");
    return (
      <Tooltip title={tooltip}>
        <div
          className={styles.activeMode}
          aria-live="polite"
          data-state={sessionState}
        >
          {sessionState === "starting" && (
            <LoaderCircle className={styles.spin} size={14} />
          )}
          {sessionState === "running" && <ModeIcon mode={activeMode} />}
          {sessionState === "awaiting_user" && (
            <MessageCircleQuestion size={14} />
          )}
          <span>{resolveLoopModeName(activeMode, t, lang)}</span>
          <span className={styles.activeState}>
            {t(`loop.${sessionState}`)}
          </span>
        </div>
      </Tooltip>
    );
  }

  const renderGroup = (title: string, modes: LoopModeInfo[]) => {
    if (modes.length === 0) return null;
    return (
      <section className={styles.modeGroup}>
        <div className={styles.groupLabel}>{title}</div>
        {modes.map((mode) => {
          const selected = mode.id === selectedMode.id;
          return (
            <button
              aria-selected={selected}
              className={`${styles.modeOption} ${
                selected ? styles.selected : ""
              }`}
              key={mode.id}
              onClick={() => {
                setSelectedMode(mode.id);
                setOpen(false);
              }}
              role="option"
              type="button"
            >
              <span className={styles.optionIcon}>
                <ModeIcon mode={mode} size={16} />
              </span>
              <span className={styles.optionCopy}>
                <span className={styles.optionName}>
                  {resolveLoopModeName(mode, t, lang)}
                </span>
                <span className={styles.optionDescription}>
                  <InlineMarkdown
                    markdown={resolveLoopModeDescriptionMarkdown(mode, t, lang)}
                  />
                </span>
              </span>
              {selected ? <CircleDot size={15} /> : null}
            </button>
          );
        })}
      </section>
    );
  };

  const content = (
    <div className={styles.modeMenu} role="listbox">
      <div className={styles.menuHeader}>
        <div>
          <div className={styles.menuTitle}>{t("loop.selectorTitle")}</div>
          <div className={styles.menuHint}>{t("loop.selectorHint")}</div>
        </div>
        <Tooltip title={t("loop.gotoSettings")}>
          <button
            aria-label={t("loop.gotoSettings")}
            className={styles.settingsButton}
            onClick={() => {
              setOpen(false);
              navigate("/agent-config?tab=agentLoop");
            }}
            type="button"
          >
            <Settings2 size={16} />
          </button>
        </Tooltip>
      </div>
      {renderGroup(t("loop.builtInModes"), builtInModes)}
      {renderGroup(t("loop.customModes"), extendedModes)}
      {catalogError ? (
        <div className={styles.menuError}>
          <span>{t("loop.loadError")}</span>
          <button onClick={() => void fetchAvailableLoopModes()} type="button">
            {t("loop.retry")}
          </button>
        </div>
      ) : null}
    </div>
  );

  return (
    <Popover
      arrow={false}
      content={content}
      onOpenChange={setOpen}
      open={open}
      overlayClassName={styles.modePopover}
      placement="topLeft"
      trigger="click"
    >
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={t("loop.selectorAria")}
        className={styles.modeTrigger}
        disabled={catalogLoading && availableModes.length === 0}
        type="button"
      >
        {catalogLoading ? (
          <LoaderCircle className={styles.spin} size={14} />
        ) : (
          <ModeIcon mode={selectedMode} />
        )}
        <span>{resolveLoopModeName(selectedMode, t, lang)}</span>
        <ChevronDown size={13} />
      </button>
    </Popover>
  );
}
