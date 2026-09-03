import { useEffect, useRef, useState } from "react";
import { Button, Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { Brain, Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import sessionApi from "../sessionApi";

import styles from "./ThinkingLevelToggle.module.less";

export type SessionThinkingLevel = "off" | "low" | "medium" | "high";

const LEVELS: SessionThinkingLevel[] = ["off", "low", "medium", "high"];

interface ThinkingLevelToggleProps {
  agentId?: string;
  sessionId: string;
  compact?: boolean;
  supportsThinking?: boolean;
  onChange?: (level: SessionThinkingLevel | null) => void;
}

export default function ThinkingLevelToggle({
  agentId,
  sessionId,
  compact = false,
  supportsThinking = false,
  onChange,
}: ThinkingLevelToggleProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [level, setLevel] = useState<SessionThinkingLevel | null>(null);
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null);
  const [loadedAgentId, setLoadedAgentId] = useState<string | undefined>();
  const onChangeRef = useRef(onChange);
  const saveRequestRef = useRef(0);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (loadedAgentId !== agentId || loadedSessionId !== sessionId) return;
    onChangeRef.current?.(supportsThinking ? level : null);
  }, [
    agentId,
    level,
    loadedAgentId,
    loadedSessionId,
    sessionId,
    supportsThinking,
  ]);

  useEffect(() => {
    saveRequestRef.current += 1;
  }, [agentId, sessionId]);

  useEffect(() => {
    let active = true;
    setLoadedSessionId(null);
    setLoadedAgentId(undefined);
    const load = async () => {
      try {
        await sessionApi.getSessionList();
      } catch {
        // Use cached metadata when the Session list cannot be refreshed.
      }
      if (!active) return;
      const saved = sessionApi.getSessionMeta(sessionId).thinking_level;
      const next = LEVELS.includes(saved as SessionThinkingLevel)
        ? (saved as SessionThinkingLevel)
        : null;
      setLevel(next);
      setLoadedSessionId(sessionId);
      setLoadedAgentId(agentId);
    };
    void load();
    return () => {
      active = false;
    };
  }, [agentId, sessionId]);

  const handleSelect = async (next: SessionThinkingLevel) => {
    if (loadedAgentId !== agentId || loadedSessionId !== sessionId) return;
    const previousLevel = level;
    const requestId = ++saveRequestRef.current;
    setLevel(next);
    onChangeRef.current?.(next);
    const meta = sessionApi.getSessionMeta(sessionId);
    try {
      await sessionApi.updateSessionMeta(sessionId, {
        ...meta,
        thinking_level: next,
      });
    } catch (error) {
      if (requestId !== saveRequestRef.current) return;
      setLevel(previousLevel);
      onChangeRef.current?.(supportsThinking ? previousLevel : null);
      message.error(
        error instanceof Error ? error.message : t("sessions.saveFailed"),
      );
    }
  };

  const menuItems: MenuProps["items"] = LEVELS.map((item) => ({
    key: item,
    label: (
      <span className={styles.menuItem}>
        <span>{t(`modelSelector.thinking.${item}`)}</span>
        {item === level && <Check size={14} aria-hidden="true" />}
      </span>
    ),
    onClick: () => void handleSelect(item),
  }));

  if (!supportsThinking) return null;

  return (
    <Tooltip title={t("chat.thinkingLevelTitle")}>
      <Dropdown
        menu={{ items: menuItems, selectedKeys: level ? [level] : [] }}
        trigger={["click"]}
      >
        <Button
          size="small"
          aria-label={t("chat.thinkingLevelTitle")}
          style={{
            height: compact ? 30 : undefined,
            paddingInline: compact ? 0 : undefined,
            width: compact ? 30 : undefined,
          }}
          disabled={loadedAgentId !== agentId || loadedSessionId !== sessionId}
        >
          <Brain size={13} />
          {!compact && (
            <>
              {t(
                level
                  ? `modelSelector.thinking.${level}`
                  : "modelSelector.thinking.inherit",
              )}
              <ChevronDown size={11} />
            </>
          )}
        </Button>
      </Dropdown>
    </Tooltip>
  );
}
