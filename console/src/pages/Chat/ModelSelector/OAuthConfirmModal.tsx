import { useState, useEffect, useCallback, useRef } from "react";
import { Modal, Button } from "@agentscope-ai/design";
import { Loader2, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  openExternalLink,
  isDesktopTauriRuntime,
} from "../../../utils/openExternalLink";

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

  useEffect(() => {
    if (!open) {
      setPhase("confirm");
      if (pollRef.current) clearInterval(pollRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    }
  }, [open]);

  const handleContinue = useCallback(async () => {
    try {
      const { authorize_url, state } = await providerApi.startOAuth(providerId);
      setPhase("waiting");

      const isDesktop = isDesktopTauriRuntime();
      let popup: Window | null = null;

      if (isDesktop) {
        openExternalLink(authorize_url);
      } else {
        popup = window.open(
          authorize_url,
          "_blank",
          "popup,width=600,height=700",
        );
      }

      // postMessage listener (works in browser, not in desktop)
      const messageHandler = (event: MessageEvent) => {
        if (
          event.data?.type === "oauth_complete" &&
          event.data.provider === providerId
        ) {
          cleanup();
          message.success(
            t("modelSelector.oauthConnected", { provider: providerName }),
          );
          onSuccess();
        }
      };
      if (!isDesktop) {
        window.addEventListener("message", messageHandler);
      }

      const cleanup = () => {
        if (pollRef.current) clearInterval(pollRef.current);
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        window.removeEventListener("message", messageHandler);
      };

      // Poll status (primary mechanism for desktop, fallback for browser)
      pollRef.current = setInterval(async () => {
        try {
          const { status } = await providerApi.getOAuthStatus(
            providerId,
            state,
          );
          if (status === "completed") {
            cleanup();
            popup?.close();
            message.success(
              t("modelSelector.oauthConnected", { provider: providerName }),
            );
            onSuccess();
          } else if (status === "failed") {
            cleanup();
            popup?.close();
            message.error(t("modelSelector.oauthFailed"));
            onCancel();
          }
        } catch {
          // Ignore polling errors
        }
      }, 2000);

      // Timeout after 5 minutes
      timeoutRef.current = setTimeout(() => {
        cleanup();
      }, 300000);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("modelSelector.oauthFailed"),
      );
      onCancel();
    }
  }, [providerId, providerName, onSuccess, onCancel, message, t]);

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
        <div style={{ textAlign: "center", padding: "16px 0" }}>
          <ExternalLink
            size={40}
            style={{ color: "#6366f1", marginBottom: 16 }}
          />
          <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 600 }}>
            {t("modelSelector.oauthTitle", { provider: providerName })}
          </h3>
          <p style={{ color: "var(--text-secondary)", margin: "0 0 24px" }}>
            {t("modelSelector.oauthDescription", { provider: providerName })}
          </p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
            <Button onClick={onCancel}>{t("common.cancel")}</Button>
            <Button type="primary" onClick={handleContinue}>
              {t("modelSelector.oauthContinue")}
            </Button>
          </div>
        </div>
      ) : (
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <Loader2
            size={32}
            style={{ color: "#6366f1", animation: "spin 1s linear infinite" }}
          />
          <h3 style={{ margin: "16px 0 8px", fontSize: 16, fontWeight: 600 }}>
            {t("modelSelector.oauthWaiting")}
          </h3>
          <p style={{ color: "var(--text-secondary)", margin: "0 0 24px" }}>
            {t("modelSelector.oauthWaitingDescription")}
          </p>
          <Button onClick={onCancel}>{t("common.cancel")}</Button>
        </div>
      )}
    </Modal>
  );
}
