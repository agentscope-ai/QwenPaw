import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import {
  AlertTriangle,
  Ban,
  Check,
  CheckCircle,
  ChevronDown,
  Shield,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  LEVELS,
  normalizeLevel,
  type ToolExecutionLevel,
} from "../../../utils/approval";
import { useIsMobile } from "../../../hooks/useIsMobile";
import { OsDrawer } from "../../../os/OsOverlay";
import drawerStyles from "./ApprovalToggle.module.less";

const LEVEL_META: Record<
  ToolExecutionLevel,
  { color: string; icon: React.ReactNode }
> = {
  STRICT: { color: "#ff4d4f", icon: <Ban size={12} /> },
  SMART: { color: "#faad14", icon: <AlertTriangle size={12} /> },
  AUTO: { color: "#1890ff", icon: <Shield size={12} /> },
  OFF: { color: "#52c41a", icon: <CheckCircle size={12} /> },
};

function storageKey(chatId: string): string {
  return `approval_level-${chatId}`;
}

interface ApprovalLevelToggleProps {
  /** Use queueSessionId (chatId ?? "new") for consistent storage key */
  sessionId: string;
  /** Default level from GET /workspace/running-config */
  runningConfigApprovalLevel: ToolExecutionLevel;
  /** null = no session override, backend uses running-config */
  onChange?: (sessionOverride: ToolExecutionLevel | null) => void;
  compact?: boolean;
  className?: string;
}

const ApprovalLevelToggle: React.FC<ApprovalLevelToggleProps> = ({
  sessionId,
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
  const prevSessionIdRef = useRef<string>(sessionId);

  useEffect(() => {
    const prevSessionId = prevSessionIdRef.current;

    // Migrate from temporary sessionId (including "new" or localId) to real backend chatId
    // This happens when:
    // 1. "new" -> real UUID (first message sent)
    // 2. localId (timestamp-random) -> real UUID (session resolved)
    if (prevSessionId !== sessionId) {
      const isLocalId = (id: string) =>
        id === "new" || /^\d{13}-[a-z0-9]{7}$/.test(id);
      const isRealId = (id: string) => id.length === 36 && id.includes("-");

      // Migrate if transitioning from local/temp to real
      if (isLocalId(prevSessionId) && isRealId(sessionId)) {
        const prevLevel = localStorage.getItem(storageKey(prevSessionId));
        if (prevLevel && LEVELS.includes(prevLevel as ToolExecutionLevel)) {
          localStorage.setItem(storageKey(sessionId), prevLevel);
          localStorage.removeItem(storageKey(prevSessionId));
        }
      }
    }

    prevSessionIdRef.current = sessionId;

    const saved = localStorage.getItem(storageKey(sessionId));
    if (saved && LEVELS.includes(saved as ToolExecutionLevel)) {
      setSessionLevel(saved as ToolExecutionLevel);
    } else {
      setSessionLevel(null);
    }
  }, [sessionId]);

  const effectiveLevel = sessionLevel ?? runningConfigApprovalLevel;
  const meta = LEVEL_META[effectiveLevel];

  useEffect(() => {
    onChangeRef.current?.(sessionLevel);
  }, [sessionLevel]);

  const handleSelect = useCallback(
    (level: ToolExecutionLevel) => {
      setSessionLevel(level);
      setOpen(false);
      localStorage.setItem(storageKey(sessionId), level);
      onChangeRef.current?.(level);
    },
    [sessionId],
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

    return items;
  }, [handleSelect, t]);

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
