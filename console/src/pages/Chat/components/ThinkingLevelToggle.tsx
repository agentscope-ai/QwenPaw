import { useEffect, useRef, useState } from "react";
import { Button, Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { Brain, Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import sessionApi from "../sessionApi";

export type SessionThinkingLevel = "off" | "low" | "medium" | "high";

const LEVELS: SessionThinkingLevel[] = ["off", "low", "medium", "high"];

interface ThinkingLevelToggleProps {
  sessionId: string;
  compact?: boolean;
  onChange?: (level: SessionThinkingLevel | null) => void;
}

export default function ThinkingLevelToggle({
  sessionId,
  compact = false,
  onChange,
}: ThinkingLevelToggleProps) {
  const { t } = useTranslation();
  const [level, setLevel] = useState<SessionThinkingLevel>("medium");
  const [supportsThinking, setSupportsThinking] = useState(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const supported = (
      window as Window & { __qwenpawModelSupportsThinking?: boolean }
    ).__qwenpawModelSupportsThinking;
    if (supported === true) {
      setSupportsThinking(true);
      onChangeRef.current?.(level);
    }
  }, [level]);

  useEffect(() => {
    let active = true;
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
        : "medium";
      setLevel(next);
      onChangeRef.current?.(next);
    };
    void load();
    return () => {
      active = false;
    };
  }, [sessionId]);

  useEffect(() => {
    const handleModelSwitch = (event: Event) => {
      const detail = (event as CustomEvent<{ supportsThinking?: boolean }>)
        .detail;
      const supported = detail?.supportsThinking === true;
      setSupportsThinking(supported);
      onChangeRef.current?.(supported ? level : null);
    };
    window.addEventListener(
      "model-thinking-support-changed",
      handleModelSwitch,
    );
    return () =>
      window.removeEventListener(
        "model-thinking-support-changed",
        handleModelSwitch,
      );
  }, [level]);

  const handleSelect = async (next: SessionThinkingLevel) => {
    setLevel(next);
    onChangeRef.current?.(next);
    const meta = sessionApi.getSessionMeta(sessionId);
    try {
      await sessionApi.updateSessionMeta(sessionId, {
        ...meta,
        thinking_level: next,
      });
    } catch {
      // The next chat request persists the selected Session value.
    }
  };

  const menuItems: MenuProps["items"] = LEVELS.map((item) => ({
    key: item,
    label: t(`modelSelector.thinking.${item}`),
    icon: item === level ? <Check size={14} /> : undefined,
    onClick: () => void handleSelect(item),
  }));

  if (!supportsThinking) return null;

  return (
    <Tooltip title={t("chat.thinkingLevelTitle")}>
      <Dropdown
        menu={{ items: menuItems, selectedKeys: [level] }}
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
        >
          <Brain size={13} />
          {!compact && (
            <>
              {t(`modelSelector.thinking.${level}`)}
              <ChevronDown size={11} />
            </>
          )}
        </Button>
      </Dropdown>
    </Tooltip>
  );
}
