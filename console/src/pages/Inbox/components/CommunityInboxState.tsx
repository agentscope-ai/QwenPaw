import { useCallback, useEffect, useState } from "react";
import { Alert, Button } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "@/api/modules/community";
import { communityErrorKey } from "@/utils/communityError";
import { INBOX_CHANGED_EVENT, notifyInboxChanged } from "@/utils/inboxEvents";

/** Community connection state stays separate from local/Hub authentication. */
export function CommunityInboxState() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [status, setStatus] = useState<CommunityConnectionStatus | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [requestFailed, setRequestFailed] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await communityConnectionApi.status(signal);
      if (!signal?.aborted) {
        setStatus(next);
        setRequestFailed(false);
      }
    } catch {
      if (!signal?.aborted) setRequestFailed(true);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => {
      void load(controller.signal);
    };
    const refreshVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    refresh();
    const timer = window.setInterval(refreshVisible, 30000);
    window.addEventListener(INBOX_CHANGED_EVENT, refresh);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      window.removeEventListener(INBOX_CHANGED_EVENT, refresh);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [load]);

  if (!status && !requestFailed) return null;
  const disconnected = status !== null && status.status !== "connected";
  const syncFailed = !!status?.last_error || requestFailed;
  const paused =
    status?.status === "connected" &&
    (!status.sync_enabled || !status.messages_enabled);
  if (!disconnected && !syncFailed && !paused) return null;
  const retry = async () => {
    setRetrying(true);
    try {
      if (
        status?.status === "connected" &&
        status.sync_enabled &&
        status.messages_enabled
      )
        await communityConnectionApi.sync();
      await load();
      notifyInboxChanged();
    } catch {
      setRequestFailed(true);
    } finally {
      setRetrying(false);
    }
  };
  return (
    <Alert
      style={{ marginBottom: 12 }}
      showIcon
      type={syncFailed ? "warning" : "info"}
      message={t(
        disconnected
          ? "communityInbox.connectHint"
          : syncFailed
          ? "communityInbox.syncFailed"
          : paused
          ? "communityInbox.syncPaused"
          : "communityInbox.connectHint",
      )}
      description={
        status?.last_error ? t(communityErrorKey(status.last_error)) : undefined
      }
      action={
        syncFailed && !disconnected ? (
          <Button size="small" loading={retrying} onClick={() => void retry()}>
            {t("common.retry")}
          </Button>
        ) : (
          <Button size="small" onClick={() => navigate("/community-settings")}>
            {t(
              disconnected
                ? "communityInbox.connect"
                : "communityInbox.settings",
            )}
          </Button>
        )
      }
    />
  );
}
