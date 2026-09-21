import { ModelPickerPopover } from "../../pages/Chat/ModelSelector/ModelPickerPopover";
import { useEffect, useRef, useState } from "react";
import { Spin, Tooltip } from "antd";
import { ChevronDown, ArrowLeft, RotateCcw, Plug } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { ThinkingControl } from "./ThinkingControl";
import {
  readPendingThinking,
  sessionThinkingApi,
  setPendingThinking,
} from "./sessionThinkingApi";
import type { ThinkingPreference, ThinkingView } from "./types";
import {
  readPendingModel,
  resetSessionModel,
} from "../session-settings/sessionModel";
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
  const [preview, setPreview] = useState<ThinkingPreference>();
  const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const identity = `${agentId}:${sessionId}:${chatId ?? ""}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  useEffect(() => {
    setOpen(false);
    setChoosing(false);
    setView(undefined);
    setPreview(undefined);
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
      if (!chatId || readPendingModel(agentId, sessionId))
        next.value =
          readPendingThinking(agentId, sessionId, next.model_key) ?? next.value;
      setPreview(undefined);
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
    setPreview(value);
    const version = ++revision.current;
    if (!chatId) {
      setPendingThinking(agentId, sessionId, value, view.model_key);
      setView({ ...view, value, reason: null });
      setPreview(undefined);
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
      if (identityRef.current === identity && revision.current === version) {
        setBusy(false);
        setPreview(undefined);
      }
    }
  }
  const canReset =
    !!view &&
    (view.model_source === "session" || view.value.level !== "inherit");
  async function resetModel() {
    if (busy || !canReset) return;
    setBusy(true);
    try {
      await resetSessionModel(agentId, { sessionId, chatId });
      if (identityRef.current !== identity) return;
      setChoosing(false);
      await load();
      window.dispatchEvent(new Event("session-model-changed"));
    } catch (error) {
      if (identityRef.current === identity) message.error(String(error));
    } finally {
      if (identityRef.current === identity) setBusy(false);
    }
  }
  const resetModelButton = (
    <Tooltip title={t("thinkingControl.resetModel")}>
      <button
        type="button"
        className={styles.iconButton}
        aria-label={t("thinkingControl.resetModel")}
        disabled={busy || !canReset}
        onClick={() => void resetModel()}
      >
        <RotateCcw size={15} />
      </button>
    </Tooltip>
  );
  const value = view?.value ?? { level: "inherit" as const };
  const displayedValue = preview ?? value;
  const display =
    displayedValue.level === "inherit"
      ? view?.effective ?? displayedValue
      : displayedValue;
  const showPicker = choosing || (!!view && !view.model);
  return (
    <ModelPickerPopover
      picker={showPicker}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setChoosing(false);
          setPreview(undefined);
        }
        if (next) void load();
      }}
      content={
        <div className={showPicker ? styles.picker : styles.popover}>
          {showPicker ? (
            <>
              {view?.model && (
                <div className={styles.back}>
                  <button
                    type="button"
                    className={styles.iconButton}
                    aria-label={t("common.back")}
                    onClick={() => setChoosing(false)}
                  >
                    <ArrowLeft size={17} />
                  </button>
                  {resetModelButton}
                </div>
              )}
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
              {view?.model && (
                <ThinkingControl
                  control={view.control}
                  value={value}
                  effective={view.effective}
                  modelLabel={
                    view.model_name ||
                    (view.provider_id === "hub-managed"
                      ? undefined
                      : view.model) ||
                    t("modelSelector.selectModel")
                  }
                  resetAction={resetModelButton}
                  onChooseModel={() => setChoosing(true)}
                  onPreview={setPreview}
                  onChange={(next) => void save(next)}
                  disabled={busy}
                />
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
        {view && !view.model && <Plug size={16} aria-hidden="true" />}
        <span>
          {view?.model_name ||
            (view?.provider_id !== "hub-managed" ? view?.model : undefined) ||
            t("modelSelector.selectModel")}
        </span>
        {view?.model && (
          <ThinkingIndicator control={view.control} value={display} />
        )}
        <ChevronDown size={12} />
      </button>
    </ModelPickerPopover>
  );
}
