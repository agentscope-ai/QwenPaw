import { useState, useEffect, useCallback, useRef } from "react";
import { Modal, Button } from "@agentscope-ai/design";
import { Loader2, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { openExternalLink } from "../../../utils/openExternalLink";
import styles from "./index.module.less";

export interface OAuthFlow {
  start: () => Promise<{ authorize_url: string; state: string }>;
  getStatus: (state: string) => Promise<{ status: string }>;
  cancel: (state: string) => Promise<unknown>;
}

interface OAuthConfirmModalProps {
  open: boolean;
  providerId: string;
  providerName: string;
  className?: string;
  flow?: OAuthFlow;
  description?: string;
  onSuccess: () => void;
  onCancel: () => void;
}

export function OAuthConfirmModal({
  open,
  providerId,
  providerName,
  className,
  flow,
  description,
  onSuccess,
  onCancel,
}: OAuthConfirmModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [phase, setPhase] = useState<"confirm" | "waiting">("confirm");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guards in-flight poll/start responses that resolve after close or
  // unmount so a late "completed" cannot fire onSuccess (and
  // navigation) from a dead modal. True whenever the modal is not the
  // open, live instance.
  const disposedRef = useRef(!open);
  const startingRef = useRef(false);
  const generationRef = useRef(0);
  const cancelRef = useRef<(() => Promise<unknown>) | null>(null);
  const cancelAttempt = useCallback(() => {
    const cancel = cancelRef.current;
    cancelRef.current = null;
    void cancel?.().catch(() => undefined);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    pollRef.current = null;
    timeoutRef.current = null;
  }, []);

  useEffect(() => {
    // Only an open modal is live: parents keep this component mounted
    // and toggle `open`, so the close transition must leave the guard
    // set or a late poll response would act on a dismissed modal.
    disposedRef.current = !open;
    if (!open) {
      setPhase("confirm");
      startingRef.current = false;
      stopPolling();
    }
    return () => {
      disposedRef.current = true;
      generationRef.current += 1;
      stopPolling();
      cancelAttempt();
    };
  }, [open, stopPolling, cancelAttempt]);

  const handleContinue = useCallback(async () => {
    if (startingRef.current) return; // ignore double-clicks
    startingRef.current = true;
    const generation = generationRef.current;
    const isStale = () =>
      disposedRef.current || generation !== generationRef.current;
    try {
      const { authorize_url, state } = await (flow
        ? flow.start()
        : providerApi.startOAuth(providerId));
      if (isStale()) {
        void flow?.cancel(state).catch(() => undefined);
        return;
      }
      cancelRef.current = flow ? () => flow.cancel(state) : null;
      // Never stack timers from overlapping starts: the previous ids
      // would be overwritten and leak unclearable.
      stopPolling();
      setPhase("waiting");

      openExternalLink(authorize_url, "_blank", "popup,width=600,height=700");

      // Poll backend status until completion (same pattern as MCP OAuth)
      pollRef.current = setInterval(async () => {
        try {
          const { status } = await (flow
            ? flow.getStatus(state)
            : providerApi.getOAuthStatus(providerId, state));
          if (isStale()) return;
          if (status === "completed") {
            cancelRef.current = null;
            disposedRef.current = true;
            stopPolling();
            message.success(
              t("modelSelector.oauthConnected", { provider: providerName }),
            );
            onSuccess();
          } else if (status === "failed" || status === "cancelled") {
            stopPolling();
            cancelAttempt();
            disposedRef.current = true;
            message.error(t("modelSelector.oauthFailed"));
            onCancel();
          }
        } catch {
          // Ignore polling errors
        }
      }, 2000);

      // Timeout after 5 minutes: leave the user an explanation and a
      // way out instead of an eternal spinner.
      timeoutRef.current = setTimeout(() => {
        stopPolling();
        if (isStale()) return;
        cancelAttempt();
        message.error(t("modelSelector.oauthTimeout"));
        onCancel();
      }, 300000);
    } catch (err) {
      if (!isStale()) {
        cancelAttempt();
        message.error(
          flow || !(err instanceof Error)
            ? t("modelSelector.oauthFailed")
            : err.message,
        );
        onCancel();
      }
    } finally {
      if (generation === generationRef.current) startingRef.current = false;
    }
  }, [
    providerId,
    providerName,
    flow,
    onSuccess,
    onCancel,
    message,
    t,
    stopPolling,
    cancelAttempt,
  ]);

  return (
    <Modal
      open={open}
      className={className}
      onCancel={onCancel}
      footer={null}
      closable={phase === "confirm"}
      maskClosable={phase === "confirm"}
      width={420}
    >
      {phase === "confirm" ? (
        <div className={styles.oauthModalContent}>
          <ExternalLink size={40} className={styles.oauthModalIcon} />
          <h3 className={styles.oauthModalTitle}>
            {t("modelSelector.oauthTitle", { provider: providerName })}
          </h3>
          <p className={styles.oauthModalDescription}>
            {description ??
              t("modelSelector.oauthDescription", { provider: providerName })}
          </p>
          <div className={styles.oauthModalActions}>
            <Button onClick={onCancel}>{t("common.cancel")}</Button>
            <Button type="primary" onClick={handleContinue}>
              {t("modelSelector.oauthContinue")}
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.oauthModalContent} role="status">
          <Loader2 size={32} className={styles.oauthModalSpinner} />
          <h3 className={styles.oauthModalWaitingTitle}>
            {t("modelSelector.oauthWaiting")}
          </h3>
          <p className={styles.oauthModalDescription}>
            {t("modelSelector.oauthWaitingDescription")}
          </p>
          <Button onClick={onCancel}>{t("common.cancel")}</Button>
        </div>
      )}
    </Modal>
  );
}
