import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Dropdown, Tooltip, message } from "antd";
import type { MenuProps } from "antd";
import {
  AlertTriangle,
  Ban,
  Check,
  CheckCircle,
  ChevronDown,
  RotateCcw,
  Shield,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  LEVELS,
  normalizeLevel,
  type ToolExecutionLevel,
} from "../../../utils/approval";
import { chatApi } from "../../../api/modules/chat";
import { useIsMobile } from "../../../hooks/useIsMobile";
import { OsDrawer } from "../../../os/OsOverlay";
import drawerStyles from "./ApprovalToggle.module.less";

const LEVEL_META: Record<
  ToolExecutionLevel,
  { color: string; icon: React.ReactNode }
> = {
  STRICT: { color: "#ff4d4f", icon: <Ban size={12} /> },
  SMART: { color: "#faad14", icon: <AlertTriangle size={12} /> },
  AUTO: { color: "var(--app-accent-text)", icon: <Shield size={12} /> },
  OFF: { color: "#52c41a", icon: <CheckCircle size={12} /> },
};

function storageKey(chatId: string): string {
  return `approval_level-${chatId}`;
}

function isDraftSession(sessionId: string): boolean {
  return (
    sessionId === "new" ||
    sessionId.startsWith("draft:") ||
    sessionId.startsWith("new:")
  );
}

interface ApprovalLevelToggleProps {
  /** Agent-scoped draft key or canonical Chat UUID. */
  sessionId: string;
  /** Agent id for the X-Agent-Id header (used to reach the chat's
   * server-side level for existing chats). */
  agentId?: string;
  /** Default level from GET /workspace/running-config */
  runningConfigApprovalLevel: ToolExecutionLevel;
  /** null = no session override, backend uses running-config */
  onChange?: (sessionOverride: ToolExecutionLevel | null) => void;
  compact?: boolean;
  className?: string;
}

const ApprovalLevelToggle: React.FC<ApprovalLevelToggleProps> = ({
  sessionId,
  agentId,
  runningConfigApprovalLevel,
  onChange,
  compact = false,
  className,
}) => {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const [sessionLevel, setSessionLevel] = useState<ToolExecutionLevel | null>(
    null,
  );
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  // While the server-side level is being loaded, a user selection must win:
  // a stale response must not clobber a fresh pick.
  const touchedRef = useRef(false);

  const draft = isDraftSession(sessionId);

  useEffect(() => {
    touchedRef.current = false;
    const saved = localStorage.getItem(storageKey(sessionId));
    if (saved && LEVELS.includes(saved as ToolExecutionLevel)) {
      setSessionLevel(saved as ToolExecutionLevel);
    } else {
      setSessionLevel(null);
    }
  }, [sessionId]);

  // Existing chats: the level is owned by the server (stored on the chat,
  // cross-device). Local storage is a cache/offline fallback only.
  useEffect(() => {
    if (draft) return;
    let live = true;
    chatApi
      .getApprovalLevel(sessionId, agentId)
      .then((res) => {
        if (!live || touchedRef.current) return;
        const server = res.approval_level
          ? normalizeLevel(res.approval_level)
          : null;
        // Read the cache directly — the state closure is stale across a
        // sessionId change and would leak the previous chat's level.
        const localRaw = localStorage.getItem(storageKey(sessionId));
        const local =
          localRaw && LEVELS.includes(localRaw as ToolExecutionLevel)
            ? (localRaw as ToolExecutionLevel)
            : null;
        if (server === null && local !== null) {
          // Nothing persisted yet, but this device holds a preference
          // (e.g. chosen before the chat existed and migrated over on
          // creation): adopt it onto the server and keep displaying it.
          void chatApi
            .setApprovalLevel(sessionId, local, agentId)
            .catch((err) =>
              console.warn("Could not persist chat approval level:", err),
            );
          return;
        }
        setSessionLevel(server);
        try {
          if (server) {
            localStorage.setItem(storageKey(sessionId), server);
          } else {
            localStorage.removeItem(storageKey(sessionId));
          }
        } catch {
          // Storage unavailable — the server value still applies.
        }
      })
      .catch(() => {
        // Offline / fetch failed: keep the local cache (fallback).
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agentId, draft]);

  const effectiveLevel = sessionLevel ?? runningConfigApprovalLevel;
  const meta = LEVEL_META[effectiveLevel];

  useEffect(() => {
    onChangeRef.current?.(sessionLevel);
  }, [sessionLevel]);

  const persist = useCallback(
    (level: ToolExecutionLevel | null, before: ToolExecutionLevel | null) => {
      if (draft) return;
      void chatApi.setApprovalLevel(sessionId, level, agentId).catch((err) => {
        console.warn("Could not persist chat approval level:", err);
        // The level is a security control: a failed write must not leave
        // the UI showing a level the server never stored (the chat would
        // silently run at the wrong level). Roll back to the previous
        // level unless the user picked again in the meantime.
        setSessionLevel((current) => (current === level ? before : current));
        message.error(
          t(
            "agentConfig.toolExecutionLevel.persistFailed",
            "Failed to save the approval level; reverted to the previous one.",
          ),
        );
      });
    },
    [draft, sessionId, agentId, t],
  );

  const handleSelect = useCallback(
    (level: ToolExecutionLevel) => {
      const before = sessionLevel;
      touchedRef.current = true;
      setSessionLevel(level);
      setOpen(false);
      try {
        localStorage.setItem(storageKey(sessionId), level);
      } catch {
        // Storage unavailable — the pick still applies for this view.
      }
      persist(level, before);
      onChangeRef.current?.(level);
    },
    [sessionId, sessionLevel, persist],
  );

  const handleReset = useCallback(() => {
    const before = sessionLevel;
    touchedRef.current = true;
    setSessionLevel(null);
    setOpen(false);
    try {
      localStorage.removeItem(storageKey(sessionId));
    } catch {
      // Storage unavailable — the pick still applies for this view.
    }
    persist(null, before);
    onChangeRef.current?.(null);
  }, [sessionId, sessionLevel, persist]);

  const followAgentLabel = t(
    "agentConfig.toolExecutionLevel.followAgent",
    "Follow agent default",
  );

  const menuItems: MenuProps["items"] = useMemo(() => {
    const items: MenuProps["items"] = [];

    for (const lv of LEVELS) {
      const m = LEVEL_META[lv];
      const name = t(`agentConfig.toolExecutionLevel.${lv.toLowerCase()}`, lv);
      const desc = t(
        `agentConfig.toolExecutionLevel.${lv.toLowerCase()}Desc`,
        "",
      );
      items.push({
        key: lv,
        label: (
          <div>
            <div>{name}</div>
            {desc && (
              <div style={{ fontSize: 12, color: "#999", marginTop: 2 }}>
                {desc}
              </div>
            )}
          </div>
        ),
        icon: React.cloneElement(m.icon as React.ReactElement, {
          style: { color: m.color, marginTop: desc ? 4 : 0 },
        }),
        onClick: () => handleSelect(lv),
      });
    }

    if (sessionLevel !== null) {
      items.push({ type: "divider" });
      items.push({
        key: "follow-agent",
        label: (
          <div>
            <div>{followAgentLabel}</div>
            <div style={{ fontSize: 12, color: "#999", marginTop: 2 }}>
              {t(
                "agentConfig.toolExecutionLevel.followAgentDesc",
                "Use the level configured for this agent",
              )}
            </div>
          </div>
        ),
        icon: (
          <RotateCcw
            size={12}
            style={{ color: "var(--app-accent-text)", marginTop: 4 }}
          />
        ),
        onClick: handleReset,
      });
    }

    return items;
  }, [handleSelect, handleReset, sessionLevel, followAgentLabel, t]);

  const trigger = (
    <button
      className={[drawerStyles.trigger, className].filter(Boolean).join(" ")}
      aria-expanded={open}
      aria-haspopup="listbox"
      aria-label={t("agentConfig.toolExecutionLevelTitle")}
      onClick={isMobile ? () => setOpen((current) => !current) : undefined}
      type="button"
      style={{
        cursor: "pointer",
        userSelect: "none",
        borderColor: meta.color,
        color: meta.color,
        transition: "all 0.2s",
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        lineHeight: "22px",
        width: compact ? 30 : undefined,
        height: compact ? 30 : undefined,
        padding: compact ? 0 : undefined,
        marginInlineEnd: 0,
        justifyContent: "center",
      }}
    >
      {meta.icon}
      {!compact && (
        <>
          {t(
            `agentConfig.toolExecutionLevel.${effectiveLevel.toLowerCase()}`,
            effectiveLevel,
          )}
          <ChevronDown size={12} />
        </>
      )}
    </button>
  );

  if (isMobile) {
    return (
      <>
        {trigger}
        <OsDrawer
          aria-label={t("agentConfig.toolExecutionLevelTitle")}
          open={open}
          placement="bottom"
          height="auto"
          closable={false}
          destroyOnHidden
          onClose={() => setOpen(false)}
          styles={{
            body: { padding: 0, overflow: "hidden" },
            content: {
              borderRadius: "14px 14px 0 0",
              overflow: "hidden",
            },
            wrapper: { maxHeight: "min(52dvh, 430px)" },
          }}
        >
          <div className={drawerStyles.sheet}>
            <div className={drawerStyles.sheetHeader}>
              <strong>{t("agentConfig.toolExecutionLevelTitle")}</strong>
              <button
                type="button"
                aria-label={t("common.close")}
                className={drawerStyles.closeButton}
                onClick={() => setOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <div className={drawerStyles.optionList} role="listbox">
              {LEVELS.map((level) => {
                const levelMeta = LEVEL_META[level];
                const name = t(
                  `agentConfig.toolExecutionLevel.${level.toLowerCase()}`,
                  level,
                );
                const description = t(
                  `agentConfig.toolExecutionLevel.${level.toLowerCase()}Desc`,
                  "",
                );
                const selected = level === effectiveLevel;
                return (
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`${drawerStyles.option} ${
                      selected ? drawerStyles.optionSelected : ""
                    }`}
                    data-level={level}
                    key={level}
                    onClick={() => handleSelect(level)}
                  >
                    <span
                      className={drawerStyles.optionIcon}
                      style={{ color: levelMeta.color }}
                    >
                      {levelMeta.icon}
                    </span>
                    <span className={drawerStyles.optionCopy}>
                      <strong>{name}</strong>
                      {description && <small>{description}</small>}
                    </span>
                    {selected && <Check size={16} />}
                  </button>
                );
              })}
              {sessionLevel !== null && (
                <button
                  type="button"
                  role="option"
                  aria-selected={false}
                  className={drawerStyles.option}
                  data-level="follow-agent"
                  onClick={handleReset}
                >
                  <span
                    className={drawerStyles.optionIcon}
                    style={{ color: "var(--app-accent-text)" }}
                  >
                    <RotateCcw size={14} />
                  </span>
                  <span className={drawerStyles.optionCopy}>
                    <strong>{followAgentLabel}</strong>
                  </span>
                </button>
              )}
            </div>
          </div>
        </OsDrawer>
      </>
    );
  }

  return (
    <Tooltip title={t("agentConfig.toolExecutionLevelTooltip")}>
      <Dropdown
        menu={{ items: menuItems, selectedKeys: [effectiveLevel] }}
        trigger={["click"]}
        open={open}
        onOpenChange={setOpen}
      >
        {trigger}
      </Dropdown>
    </Tooltip>
  );
};

export { normalizeLevel };
export default ApprovalLevelToggle;
