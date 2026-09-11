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
  X,
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
import { useIsMobile } from "../../hooks/useIsMobile";
import { OsDrawer } from "../../os/OsOverlay";
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

interface LoopModeSelectorProps {
  className?: string;
  compact?: boolean;
}

export function LoopModeSelector({
  className,
  compact = false,
}: LoopModeSelectorProps = {}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "en";
  const navigate = useNavigate();
  const isMobile = useIsMobile();
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
    const modeName = resolveLoopModeName(activeMode, t, lang);
    const tooltip =
      activeMode.source === "custom"
        ? t("loop.activeCustomDescription")
        : t("loop.activePersistentDescription");
    return (
      <Tooltip title={tooltip}>
        <div
          className={[styles.activeMode, className].filter(Boolean).join(" ")}
          aria-label={`${modeName} ${t(`loop.${sessionState}`)}`}
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
          {!compact && (
            <>
              <span>{modeName}</span>
              <span className={styles.activeState}>
                {t(`loop.${sessionState}`)}
              </span>
            </>
          )}
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

  const settingsButton = (
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
  );

  const content = (
    <div className={styles.modeMenu}>
      <div className={styles.menuHeader}>
        <div>
          <div className={styles.menuTitle}>{t("loop.selectorTitle")}</div>
          <div className={styles.menuHint}>{t("loop.selectorHint")}</div>
        </div>
        <div className={styles.menuActions}>
          {isMobile ? (
            settingsButton
          ) : (
            <Tooltip title={t("loop.gotoSettings")}>{settingsButton}</Tooltip>
          )}
          {isMobile && (
            <button
              aria-label={t("common.close")}
              className={styles.settingsButton}
              onClick={() => setOpen(false)}
              type="button"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </div>
      <div className={styles.modeList} role="listbox">
        {renderGroup(t("loop.builtInModes"), builtInModes)}
        {renderGroup(t("loop.customModes"), extendedModes)}
        {catalogError ? (
          <div className={styles.menuError}>
            <span>{t("loop.loadError")}</span>
            <button
              onClick={() => void fetchAvailableLoopModes()}
              type="button"
            >
              {t("loop.retry")}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );

  const triggerButton = (
    <button
      aria-expanded={open}
      aria-haspopup="listbox"
      aria-label={t("loop.selectorAria")}
      className={[styles.modeTrigger, className].filter(Boolean).join(" ")}
      disabled={catalogLoading && availableModes.length === 0}
      onClick={isMobile ? () => setOpen((current) => !current) : undefined}
      type="button"
    >
      {catalogLoading ? (
        <LoaderCircle className={styles.spin} size={14} />
      ) : (
        <ModeIcon mode={selectedMode} />
      )}
      {!compact && (
        <>
          <span>{resolveLoopModeName(selectedMode, t, lang)}</span>
          <ChevronDown size={13} />
        </>
      )}
    </button>
  );

  if (isMobile) {
    return (
      <>
        {triggerButton}
        <OsDrawer
          aria-label={t("loop.selectorTitle")}
          open={open}
          placement="bottom"
          height="auto"
          closable={false}
          destroyOnHidden
          rootClassName={styles.modeDrawer}
          onClose={() => setOpen(false)}
          styles={{
            body: { padding: 0, overflow: "hidden" },
            content: {
              borderRadius: "14px 14px 0 0",
              overflow: "hidden",
            },
            wrapper: { maxHeight: "min(48dvh, 400px)" },
          }}
        >
          {content}
        </OsDrawer>
      </>
    );
  }

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
      {triggerButton}
    </Popover>
  );
}
