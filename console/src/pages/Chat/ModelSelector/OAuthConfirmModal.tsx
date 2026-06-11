import { useState, useEffect, useCallback, useRef } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Loader2, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { openExternalLink } from "../../../utils/openExternalLink";

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

      openExternalLink(authorize_url, "_blank", "popup,width=600,height=700");

      // Poll backend status until completion (same pattern as MCP OAuth)
      pollRef.current = setInterval(async () => {
        try {
          const { status } = await providerApi.getOAuthStatus(
            providerId,
            state,
          );
          if (status === "completed") {
            if (pollRef.current) clearInterval(pollRef.current);
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
            message.success(
              t("modelSelector.oauthConnected", { provider: providerName }),
            );
            onSuccess();
          } else if (status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
            message.error(t("modelSelector.oauthFailed"));
            onCancel();
          }
        } catch {
          // Ignore polling errors
        }
      }, 2000);

      // Timeout after 5 minutes
      timeoutRef.current = setTimeout(() => {
        if (pollRef.current) clearInterval(pollRef.current);
      }, 300000);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("modelSelector.oauthFailed"),
      );
      onCancel();
    }
  }, [providerId, providerName, onSuccess, onCancel, message, t]);

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v && phase === "confirm") onCancel();
      }}
    >
      <DialogContent
        className="max-w-[420px]"
        onInteractOutside={
          phase !== "confirm" ? (e) => e.preventDefault() : undefined
        }
      >
        {phase === "confirm" ? (
          <>
            <DialogHeader>
              <div className="flex justify-center mb-4">
                <ExternalLink size={40} className="text-indigo-500" />
              </div>
              <DialogTitle className="text-center">
                {t("modelSelector.oauthTitle", { provider: providerName })}
              </DialogTitle>
              <DialogDescription className="text-center">
                {t("modelSelector.oauthDescription", {
                  provider: providerName,
                })}
              </DialogDescription>
            </DialogHeader>
            <div className="flex gap-3 justify-center mt-4">
              <Button variant="outline" onClick={onCancel}>
                {t("common.cancel")}
              </Button>
              <Button onClick={handleContinue}>
                {t("modelSelector.oauthContinue")}
              </Button>
            </div>
          </>
        ) : (
          <>
            <DialogHeader>
              <div className="flex justify-center mb-4">
                <Loader2 size={32} className="animate-spin text-indigo-500" />
              </div>
              <DialogTitle className="text-center">
                {t("modelSelector.oauthWaiting")}
              </DialogTitle>
              <DialogDescription className="text-center">
                {t("modelSelector.oauthWaitingDescription")}
              </DialogDescription>
            </DialogHeader>
            <div className="flex justify-center mt-4">
              <Button variant="outline" onClick={onCancel}>
                {t("common.cancel")}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
