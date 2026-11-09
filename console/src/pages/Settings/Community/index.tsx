import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Avatar,
  Button,
  Card,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  communityConnectionApi,
  type CommunityConnectionStatus,
} from "../../../api/modules/community";
import { PageHeader } from "../../../components/PageHeader";
import { notifyInboxChanged } from "../../../utils/inboxEvents";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  reserveAuthorizationWindow,
  openAuthorizationUrl,
} from "@/utils/communityAuthorization";
import { communityErrorKey } from "@/utils/communityError";
import styles from "./index.module.less";

export default function CommunitySettings() {
  const { t } = useTranslation();
  const { message, modal } = useAppMessage();
  const [status, setStatus] = useState<CommunityConnectionStatus | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const popup = useRef<Window | null>(null);
  const blankPopup = useRef(false);
  const mounted = useRef(true);
  const statusRequest = useRef<AbortController | null>(null);
  const actionPending = useRef(false);
  const observedAccount = useRef<string | null | undefined>(undefined);
  const refresh = useCallback(async (force = false) => {
    if (!mounted.current || (actionPending.current && !force)) return;
    if (statusRequest.current && !force) return;
    statusRequest.current?.abort();
    const controller = new AbortController();
    statusRequest.current = controller;
    try {
      const next = await communityConnectionApi.status(controller.signal);
      if (mounted.current && !controller.signal.aborted) {
        const accountId = next.account?.id ?? null;
        if (
          observedAccount.current !== undefined &&
          observedAccount.current !== accountId
        ) {
          notifyInboxChanged({ clearSources: ["community"] });
        }
        observedAccount.current = accountId;
        setStatus(next);
        setError(undefined);
      }
    } catch (err) {
      if (mounted.current && !controller.signal.aborted)
        setError(communityErrorKey(err));
    } finally {
      if (statusRequest.current === controller) statusRequest.current = null;
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 3000);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      statusRequest.current?.abort();
      if (blankPopup.current) popup.current?.close();
    };
  }, [refresh]);

  const run = async (action: () => Promise<unknown>) => {
    if (actionPending.current) return;
    actionPending.current = true;
    statusRequest.current?.abort();
    setBusy(true);
    try {
      await action();
      await refresh(true);
    } catch (err) {
      if (mounted.current) message.error(t(communityErrorKey(err)));
    } finally {
      actionPending.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  const connect = () => {
    if (actionPending.current) return;
    try {
      popup.current = reserveAuthorizationWindow(t("community.waiting"));
      blankPopup.current = !!popup.current;
    } catch (err) {
      message.error(t(communityErrorKey(err)));
      return;
    }
    void run(async () => {
      try {
        const flow = await communityConnectionApi.start();
        if (!mounted.current) {
          await communityConnectionApi.cancel(flow.flow_id);
          return;
        }
        try {
          await openAuthorizationUrl(flow.authorize_url, popup.current);
          blankPopup.current = false;
        } catch (err) {
          await communityConnectionApi.cancel(flow.flow_id).catch(() => {});
          throw err;
        }
      } catch (err) {
        popup.current?.close();
        popup.current = null;
        throw err;
      }
    });
  };
  const disconnect = () =>
    modal.confirm({
      title: t("community.disconnectTitle"),
      content: t("community.disconnectDescription"),
      okText: t("community.disconnect"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () =>
        run(async () => {
          await communityConnectionApi.disconnect();
          popup.current?.close();
          popup.current = null;
          observedAccount.current = null;
          notifyInboxChanged({ clearSources: ["community"] });
        }),
    });

  const pending = status?.authorization;
  const connected = status?.status === "connected";
  const unavailable =
    status?.status === "not_configured" ||
    status?.status === "unsupported_remote";
  return (
    <div className={styles.page}>
      <PageHeader parent={t("nav.settings")} current={t("community.title")} />
      <Space direction="vertical" size="large" className={styles.content}>
        {error && (
          <Alert
            type="error"
            showIcon
            message={t(error)}
            action={
              <Button onClick={() => void refresh()}>
                {t("community.retry")}
              </Button>
            }
          />
        )}
        {!status && !error && <Spin />}
        {status && (
          <>
            {unavailable && (
              <Alert
                showIcon
                type="info"
                message={t(`community.${status.status}`)}
              />
            )}
            <Card title={t("community.account")}>
              <Space direction="vertical" size="middle">
                {status.account ? (
                  <Space>
                    <Avatar src={status.account.avatar_url} />
                    <Typography.Text strong>
                      {status.account.display_name || status.account.id}
                    </Typography.Text>
                  </Space>
                ) : (
                  <Typography.Text type="secondary">
                    {t("community.disconnected")}
                  </Typography.Text>
                )}
                {status.status === "expired" && (
                  <Alert
                    type="warning"
                    showIcon
                    message={t("community.expired")}
                  />
                )}
                {pending ? (
                  <Space wrap>
                    <Typography.Text>{t("community.waiting")}</Typography.Text>
                    <Button
                      onClick={() => {
                        void openAuthorizationUrl(
                          pending.authorize_url,
                          null,
                        ).catch((err) =>
                          message.error(t(communityErrorKey(err))),
                        );
                      }}
                    >
                      {t("community.reopen")}
                    </Button>
                    <Button
                      loading={busy}
                      onClick={() =>
                        void run(async () => {
                          await communityConnectionApi.cancel(pending.flow_id);
                          popup.current?.close();
                          popup.current = null;
                        })
                      }
                    >
                      {t("common.cancel")}
                    </Button>
                  </Space>
                ) : (
                  <Space wrap>
                    <Button
                      type="primary"
                      loading={busy}
                      disabled={
                        unavailable || status.local_login_supported === false
                      }
                      onClick={connect}
                    >
                      {t(
                        connected
                          ? "community.switchAccount"
                          : "community.connect",
                      )}
                    </Button>
                    {status.account && (
                      <Button danger disabled={busy} onClick={disconnect}>
                        {t("community.disconnect")}
                      </Button>
                    )}
                  </Space>
                )}
              </Space>
            </Card>
            <Card title={t("community.syncTitle")}>
              <Space
                direction="vertical"
                size="middle"
                className={styles.fullWidth}
              >
                <Typography.Paragraph type="secondary">
                  {t("community.syncDescription")}
                </Typography.Paragraph>
                {connected && !status.messages_enabled && (
                  <Alert
                    type="info"
                    showIcon
                    message={t("community.messagesUnavailable")}
                  />
                )}
                <Space wrap>
                  <Switch
                    aria-label={t("community.syncTitle")}
                    checked={status.sync_enabled}
                    disabled={!connected || !status.messages_enabled || busy}
                    onChange={(enabled) =>
                      void run(() => communityConnectionApi.setSync(enabled))
                    }
                  />
                  <Typography.Text>
                    {t("community.pauseKeepsMessages")}
                  </Typography.Text>
                </Space>
                <Typography.Text type="secondary">
                  {t("community.typesDescription")}
                </Typography.Text>
                <Space direction="vertical" style={{ width: "100%" }}>
                  {[
                    "comments",
                    "mentions",
                    "interactions",
                    "feedback",
                    "notifications",
                  ].map((kind) => (
                    <div
                      key={kind}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 24,
                        minHeight: 36,
                        maxWidth: 400,
                      }}
                    >
                      <Typography.Text>
                        {t(`community.messageTypes.${kind}`)}
                      </Typography.Text>
                      <Switch
                        aria-label={t(`community.messageTypes.${kind}`)}
                        checked={(
                          status.message_types ?? [
                            "comments",
                            "mentions",
                            "interactions",
                            "feedback",
                            "notifications",
                          ]
                        ).includes(kind)}
                        disabled={
                          !connected || !status.messages_enabled || busy
                        }
                        onChange={(checked) =>
                          void run(() => {
                            const selected = status.message_types ?? [
                              "comments",
                              "mentions",
                              "interactions",
                              "feedback",
                              "notifications",
                            ];
                            return communityConnectionApi.setMessageTypes(
                              checked
                                ? [...selected, kind]
                                : selected.filter((value) => value !== kind),
                            );
                          })
                        }
                      />
                    </div>
                  ))}
                </Space>
                <Space wrap>
                  <Button
                    loading={busy}
                    disabled={
                      !connected ||
                      !status.messages_enabled ||
                      !status.sync_enabled
                    }
                    onClick={() =>
                      void run(async () => {
                        await communityConnectionApi.sync();
                        notifyInboxChanged();
                      })
                    }
                  >
                    {t("community.syncNow")}
                  </Button>
                  <Typography.Text type="secondary">
                    {t("community.lastSync")}:{" "}
                    {status.last_success_at
                      ? new Date(status.last_success_at * 1000).toLocaleString()
                      : t("community.neverSynced")}
                  </Typography.Text>
                </Space>
                {status.last_error && (
                  <Alert
                    type="warning"
                    showIcon
                    message={t(communityErrorKey(status.last_error))}
                  />
                )}
              </Space>
            </Card>
          </>
        )}
      </Space>
    </div>
  );
}
