import { useState, useEffect, useCallback, useRef } from "react";
import { Modal, Button } from "@agentscope-ai/design";
import { Loader2, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { openExternalLink } from "../../../utils/openExternalLink";
import styles from "./index.module.less";

interface OAuthConfirmModalProps {
  open: boolean;
  providerId: string;
  providerName: string;
  onSuccess: () => void;
  onCancel: () => void;
}

export function OAuthConfirmModal({
  open,
  providerId,
  providerName,
  onSuccess,
  onCancel,
}: OAuthConfirmModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [phase, setPhase] = useState<"confirm" | "waiting">("confirm");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guards in-flight poll responses that resolve after close/unmount so
  // a late "completed" cannot fire onSuccess (and navigation) from a
  // dead modal.
  const disposedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    pollRef.current = null;
    timeoutRef.current = null;
  }, []);

  useEffect(() => {
    disposedRef.current = false;
    if (!open) {
      setPhase("confirm");
      stopPolling();
    }
    return () => {
      disposedRef.current = true;
      stopPolling();
    };
  }, [open, stopPolling]);

  const handleContinue = useCallback(async () => {
    try {
      const { authorize_url, state } = await providerApi.startOAuth(providerId);
      setPhase("waiting");

      openExternalLink(authorize_url, "_blank", "popup,width=600,height=700");

      // Poll backend status until completion (same pattern as MCP OAuth)
      pollRef.current = setInterval(async () => {
        try {
          const { status } = await providerApi.getOAuthStatus(
            providerId,
            state,
          );
          if (disposedRef.current) return;
          if (status === "completed") {
            stopPolling();
            message.success(
              t("modelSelector.oauthConnected", { provider: providerName }),
            );
            onSuccess();
          } else if (status === "failed") {
            stopPolling();
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
        if (disposedRef.current) return;
        message.error(t("modelSelector.oauthTimeout"));
        onCancel();
      }, 300000);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("modelSelector.oauthFailed"),
      );
      onCancel();
    }
  }, [providerId, providerName, onSuccess, onCancel, message, t, stopPolling]);

  return (
    <Modal
      open={open}
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
            {t("modelSelector.oauthDescription", { provider: providerName })}
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
