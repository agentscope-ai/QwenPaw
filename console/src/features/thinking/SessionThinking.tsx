import { ModelPickerPopover } from "../../pages/Chat/ModelSelector/ModelPickerPopover";
import { useEffect, useRef, useState } from "react";
import { Collapse, Flex, Spin, Switch, Tooltip } from "antd";
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
import type {
  DecisionSettings,
  ThinkingPreference,
  ThinkingView,
} from "./types";
import {
  readPendingModel,
  resetSessionModel,
  saveDecisionSettings,
} from "../session-settings/sessionModel";
import ModelSelector from "../../pages/Chat/ModelSelector";
import { ProviderIcon } from "../../pages/Settings/Models/components/ProviderIconComponent";
import { useTurnUsageStore } from "../../pages/Chat/turnUsageStore";
import styles from "./thinking.module.less";

export function SessionThinking({
  agentId,
  sessionId,
  chatId,
  onDecisionEnabledChange,
}: {
  agentId: string;
  sessionId: string;
  chatId?: string | null;
  onDecisionEnabledChange?: (enabled: boolean | undefined) => void;
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
    onDecisionEnabledChange?.(undefined);
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
  }, [identity, onDecisionEnabledChange]);
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
      onDecisionEnabledChange?.(next.decision?.enabled);
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
  async function save(value: ThinkingPreference | DecisionSettings) {
    if (!view || busy) return;
    if ("level" in value) setPreview(value);
    const version = ++revision.current;
    setBusy(true);
    try {
      const next =
        "enabled" in value
          ? {
              ...view,
              decision: await saveDecisionSettings(
                agentId,
                { sessionId, chatId },
                value,
              ),
            }
          : chatId
          ? await sessionThinkingApi.set(agentId, chatId, value, view.model_key)
          : { ...view, value, reason: null };
      if (identityRef.current === identity && revision.current === version) {
        setView(next);
        onDecisionEnabledChange?.(next.decision?.enabled);
        if ("level" in value)
          setPendingThinking(
            agentId,
            sessionId,
            chatId ? null : value,
            view.model_key,
          );
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
  const showPicker = choosing || !view?.model;
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
              {(view?.model || canReset) && (
                <div className={styles.back}>
                  {view?.model && (
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label={t("common.back")}
                      onClick={() => setChoosing(false)}
                    >
                      <ArrowLeft size={17} />
                    </button>
                  )}
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
              <Collapse
                key={identity}
                ghost
                expandIconPosition="end"
                items={[
                  {
                    key: "advanced",
                    label: t("chat.sessionSettings.advanced"),
                    children: (
                      <Flex
                        component="label"
                        align="center"
                        justify="space-between"
                      >
                        {t("chat.sessionSettings.decisionEnabled")}
                        <Switch
                          size="small"
                          aria-label={t("chat.sessionSettings.decisionEnabled")}
                          checked={view?.decision?.enabled ?? false}
                          disabled={busy || !view?.decision?.configured}
                          onChange={(enabled) =>
                            view?.decision &&
                            void save({
                              ...view.decision,
                              enabled,
                              override: enabled,
                            })
                          }
                        />
                      </Flex>
                    ),
                  },
                ]}
              />
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
        {view?.model && display.level !== "inherit" && (
          <ThinkingIndicator control={view.control} value={display} />
        )}
        <ChevronDown size={12} />
      </button>
    </ModelPickerPopover>
  );
}
