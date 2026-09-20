import { useEffect, useRef, useState } from "react";
import { Popover, Spin, Tooltip } from "antd";
import { ChevronDown, ArrowLeft, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import { ThinkingControl } from "./ThinkingControl";
import {
  readPendingThinking,
  sessionThinkingApi,
  setPendingThinking,
} from "./sessionThinkingApi";
import type { ThinkingPreference, ThinkingView } from "./types";
import { resetSessionModel } from "../session-settings/sessionModel";
import ModelSelector from "../../pages/Chat/ModelSelector";
import { ProviderIcon } from "../../pages/Settings/Models/components/ProviderIconComponent";
import { useTurnUsageStore } from "../../pages/Chat/turnUsageStore";
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
  const [choosing, setChoosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const identity = `${agentId}:${sessionId}:${chatId ?? ""}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  useEffect(() => {
    setOpen(false);
    setChoosing(false);
    setView(undefined);
    setBusy(false);
    revision.current += 1;
    void load();
    const refresh = () => {
      void load();
    };
    window.addEventListener("session-model-changed", refresh);
    return () => {
      revision.current += 1;
      window.removeEventListener("session-model-changed", refresh);
    };
  }, [identity]);
  async function load() {
    const version = ++revision.current;
    setBusy(true);
    try {
      const next = await sessionThinkingApi.get(agentId, chatId, sessionId);
      if (identityRef.current !== identity || revision.current !== version)
        return;
      if (!chatId)
        next.value =
          readPendingThinking(agentId, sessionId, next.model_key) ?? next.value;
      setView(next);
      useTurnUsageStore
        .getState()
        .setActiveMaxInputLength(next.effective_max_input_length ?? null);
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
      setPendingThinking(agentId, sessionId, value, view.model_key);
      setView({ ...view, value, reason: null });
      return;
    }
    setBusy(true);
    try {
      const next = await sessionThinkingApi.set(
        agentId,
        chatId,
        value,
        view.model_key,
      );
      if (identityRef.current === identity && revision.current === version) {
        setView(next);
        setPendingThinking(agentId, sessionId, null, view.model_key);
      }
    } catch (error) {
      if (identityRef.current === identity) message.error(String(error));
    } finally {
      if (identityRef.current === identity && revision.current === version)
        setBusy(false);
    }
  }
  const value = view?.value ?? { level: "inherit" as const };
  const display = value.level === "inherit" ? view?.effective ?? value : value;
  return (
    <Popover
      overlayClassName={styles.overlay}
      trigger="click"
      placement="topLeft"
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setChoosing(false);
        if (next) void load();
      }}
      content={
        <div className={choosing ? styles.picker : styles.popover}>
          {choosing ? (
            <>
              <div className={styles.back}>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={t("common.back")}
                  onClick={() => setChoosing(false)}
                >
                  <ArrowLeft size={17} />
                </button>
                <span className={styles.source}>
                  {t(
                    `thinkingControl.modelSource.${
                      view?.model_source ?? "global"
                    }`,
                  )}
                </span>
                <Tooltip title={t("thinkingControl.inherit")}>
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-label={t("thinkingControl.inherit")}
                    disabled={busy || view?.model_source !== "session"}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await resetSessionModel(agentId, { sessionId, chatId });
                        setChoosing(false);
                        await load();
                        window.dispatchEvent(
                          new Event("session-model-changed"),
                        );
                      } catch (error) {
                        message.error(String(error));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    <RotateCcw size={15} />
                  </button>
                </Tooltip>
              </div>
              <ModelSelector
                embedded
                sessionId={sessionId}
                chatId={chatId}
                onSelected={() => {
                  setChoosing(false);
                  void load();
                }}
              />
            </>
          ) : (
            <Spin spinning={busy}>
              {view && (
                <ThinkingControl
                  control={view.control}
                  value={value}
                  effective={view.effective}
                  modelLabel={view.model || t("modelSelector.selectModel")}
                  onChooseModel={() => setChoosing(true)}
                  onChange={(next) => void save(next)}
                  disabled={busy}
                />
              )}
              {!view && (
                <button
                  type="button"
                  className={styles.modelChoice}
                  onClick={() => setChoosing(true)}
                >
                  {t("modelSelector.selectModel")}
                </button>
              )}
            </Spin>
          )}
        </div>
      }
    >
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-label={t("thinkingControl.title")}
      >
        {view?.provider_id && (
          <ProviderIcon providerId={view.provider_id} size={16} />
        )}
        <span>{view?.model || t("modelSelector.selectModel")}</span>
        <span
          className={styles.source}
          title={t(
            `thinkingControl.modelSource.${view?.model_source ?? "global"}`,
          )}
        >
          {display.level === "budget"
            ? `${display.budget_tokens?.toLocaleString()}`
            : t(`thinkingControl.${display.level}`)}
        </span>
        <ChevronDown size={12} />
      </button>
    </Popover>
  );
}
