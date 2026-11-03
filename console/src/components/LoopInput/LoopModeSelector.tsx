import {
  Bot,
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
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import {
  DEFAULT_LOOP_MODE,
  fetchAvailableLoopModes,
  selectLoopModeAfterExit,
  type LoopModeInfo,
  useLoopStore,
} from "../../stores/loopStore";
import { advisorModeApi } from "../../api/modules/advisorMode";
import { ADVISOR_LOOP_MODE_ID } from "../../constants/loopMode";
import { useIsMobile } from "../../hooks/useIsMobile";
import { OsDrawer } from "../../os/OsOverlay";
import { InlineMarkdown } from "../Markdown/InlineMarkdown";
import {
  resolveLoopModeDescriptionMarkdown,
  resolveLoopModeName,
} from "../../utils/loopModeDescription";
import { AdvisorSetupPopover } from "./AdvisorSetupPopover";
import styles from "./index.module.less";

function ModeIcon({ mode, size = 14 }: { mode: LoopModeInfo; size?: number }) {
  if (mode.id === ADVISOR_LOOP_MODE_ID) return <Bot size={size} />;
  if (mode.id === "goal") return <Target size={size} />;
  if (mode.id === "mission") return <Rocket size={size} />;
  if (mode.source === "custom") return <Sparkles size={size} />;
  if (mode.source === "plugin") return <Boxes size={size} />;
  return <CircleDot size={size} />;
}

interface LoopModeSelectorProps {
  className?: string;
  compact?: boolean;
  chatId?: string | null;
  agentId?: string | null;
}

interface SelectorScope {
  chatId?: string | null;
  agentId?: string | null;
  version: number;
}

export function LoopModeSelector({
  className,
  compact = false,
  chatId,
  agentId,
}: LoopModeSelectorProps = {}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "en";
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  // Opens by itself right after Advisor is picked. The chat header's
  // Advisor pill opens its own copy of the panel.
  const [advisorSetupOpen, setAdvisorSetupOpen] = useState(false);
  const [switchingScope, setSwitchingScope] = useState<SelectorScope | null>(
    null,
  );
  const [switchErrorScope, setSwitchErrorScope] =
    useState<SelectorScope | null>(null);
  const exitScopeVersion = useRef(0);
  useEffect(
    () => () => {
      exitScopeVersion.current += 1;
    },
    [chatId, agentId],
  );
  // Returning to the same chat must not revive an earlier pending request.
  const isCurrentScope = (scope: SelectorScope | null) =>
    scope !== null &&
    scope.chatId === chatId &&
    scope.agentId === agentId &&
    scope.version === exitScopeVersion.current;
  const switching = isCurrentScope(switchingScope);
  const switchError = isCurrentScope(switchErrorScope);
  const availableModes = useLoopStore((state) => state.availableModes);
  const selectedModeId = useLoopStore((state) => state.selectedModeId);
  const sessionState = useLoopStore((state) => state.sessionState);
  const activeMode = useLoopStore((state) => state.activeMode);
  const catalogLoading = useLoopStore((state) => state.catalogLoading);
  const catalogError = useLoopStore((state) => state.catalogError);
  const setSelectedMode = useLoopStore((state) => state.setSelectedMode);

  const canSwitchAdvisor =
    sessionState === "awaiting_user" &&
    activeMode?.id === ADVISOR_LOOP_MODE_ID &&
    Boolean(chatId);
  const selectedMode = canSwitchAdvisor
    ? activeMode
    : availableModes.find((mode) => mode.id === selectedModeId) ??
      DEFAULT_LOOP_MODE;
  const builtInModes = useMemo(
    () => availableModes.filter((mode) => mode.source === "builtin"),
    [availableModes],
  );
  const extendedModes = useMemo(
    () => availableModes.filter((mode) => mode.source !== "builtin"),
    [availableModes],
  );

  if (sessionState !== "idle" && activeMode && !canSwitchAdvisor) {
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
              disabled={switching}
              onClick={async () => {
                if (canSwitchAdvisor && mode.id !== activeMode?.id) {
                  const requestVersion = exitScopeVersion.current;
                  const requestScope = {
                    chatId,
                    agentId,
                    version: requestVersion,
                  };
                  setSwitchingScope(requestScope);
                  setSwitchErrorScope(null);
                  try {
                    await advisorModeApi.exitSession(chatId!);
                    if (exitScopeVersion.current !== requestVersion) return;
                    selectLoopModeAfterExit(mode.id);
                    setOpen(false);
                  } catch {
                    if (exitScopeVersion.current === requestVersion) {
                      setSwitchErrorScope(requestScope);
                    }
                  } finally {
                    if (exitScopeVersion.current === requestVersion) {
                      setSwitchingScope(null);
                    }
                  }
                  return;
                }
                setSelectedMode(mode.id);
                setOpen(false);
                if (mode.id === ADVISOR_LOOP_MODE_ID) {
                  setAdvisorSetupOpen(true);
                }
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
        {switchError ? (
          <div className={styles.menuError}>{t("loop.switchError")}</div>
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
      disabled={switching || (catalogLoading && availableModes.length === 0)}
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
          {canSwitchAdvisor && (
            <span className={styles.activeState}>
              {t("loop.awaiting_user")}
            </span>
          )}
          <ChevronDown size={13} />
        </>
      )}
    </button>
  );

  const advisorSetup =
    selectedMode.id === ADVISOR_LOOP_MODE_ID ? (
      <AdvisorSetupPopover
        open={advisorSetupOpen}
        onOpenChange={setAdvisorSetupOpen}
      />
    ) : null;

  if (isMobile) {
    return (
      <>
        {triggerButton}
        {advisorSetup}
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
    <>
      <Popover
        arrow={false}
        content={content}
        onOpenChange={setOpen}
        open={open}
        classNames={{ root: styles.modePopover }}
        placement="topLeft"
        trigger="click"
      >
        {triggerButton}
      </Popover>
      {advisorSetup}
    </>
  );
}
