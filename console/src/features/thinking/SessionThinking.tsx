import { useEffect, useRef, useState } from "react";
import { Popover, Spin } from "antd";
import { Brain, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import { ThinkingControl } from "./ThinkingControl";
import {
  readPendingThinking,
  sessionThinkingApi,
  setPendingThinking,
} from "./sessionThinkingApi";
import type { ThinkingPreference, ThinkingView } from "./types";
import InlineHelp from "../../components/InlineHelp";
import styles from "./thinking.module.less";

export function SessionThinking({
  agentId,
  sessionId,
  chatId,
}: {
  agentId: string;
  sessionId: string;
  chatId?: string | null;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [view, setView] = useState<ThinkingView>();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const identity = `${agentId}:${sessionId}:${chatId ?? ""}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  useEffect(() => {
    setOpen(false);
    setView(undefined);
    setBusy(false);
    revision.current += 1;
    void load();
  }, [identity]);
  async function load() {
    const version = ++revision.current;
    setBusy(true);
    try {
      const next = await sessionThinkingApi.get(agentId, chatId);
      if (identityRef.current !== identity || revision.current !== version)
        return;
      if (!chatId)
        next.value = readPendingThinking(agentId, sessionId) ?? next.value;
      setView(next);
    } catch (error) {
      if (identityRef.current === identity) message.error(String(error));
    } finally {
      if (identityRef.current === identity && revision.current === version)
        setBusy(false);
    }
  }
  async function save(value: ThinkingPreference) {
    if (!view || busy) return;
    const version = ++revision.current;
    if (!chatId) {
      setPendingThinking(agentId, sessionId, value);
      setView({ ...view, value, reason: null });
      return;
    }
    setBusy(true);
    try {
      const next = await sessionThinkingApi.set(agentId, chatId, value);
      if (identityRef.current === identity && revision.current === version) {
        setView(next);
        setPendingThinking(agentId, sessionId, null);
      }
    } catch (error) {
      if (identityRef.current === identity) message.error(String(error));
    } finally {
      if (identityRef.current === identity && revision.current === version)
        setBusy(false);
    }
  }
  const value = view?.value ?? { level: "inherit" as const };
  return (
    <Popover
      overlayClassName={styles.overlay}
      trigger="click"
      placement="topLeft"
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) void load();
      }}
      content={
        <div className={styles.popover}>
          <Spin spinning={busy}>
            {view ? (
              <ThinkingControl
                control={view.control}
                value={value}
                onChange={(next) => void save(next)}
                disabled={busy}
              />
            ) : (
              <p>{t("thinkingControl.title")}</p>
            )}
          </Spin>
          {view?.reason && (
            <p className={styles.hint} role="status">
              {t("thinkingControl.adapted")}
            </p>
          )}
          <div className={styles.sessionCaption}>
            <span>{view?.model}</span>
            <InlineHelp>{t("thinkingControl.sessionHint")}</InlineHelp>
          </div>
        </div>
      }
    >
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-label={t("thinkingControl.title")}
      >
        <Brain size={16} strokeWidth={1.7} />
        <span>
          {value.level === "budget"
            ? `${value.budget_tokens?.toLocaleString()}`
            : t(`thinkingControl.${value.level}`)}
        </span>
        <ChevronDown size={12} />
      </button>
    </Popover>
  );
}
